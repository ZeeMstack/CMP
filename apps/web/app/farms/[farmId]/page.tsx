"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useMemo, useState } from "react";

import { HomeInspector } from "@/components/home/HomeInspector";
import { HomeQueueView } from "@/components/home/HomeQueueView";
import { BoundedDataRegion } from "@/components/layout/BoundedDataRegion";
import { InspectorEmptyState } from "@/components/layout/InspectorShell";
import { SplitWorkspace } from "@/components/layout/SplitWorkspace";
import { ViewTabs, type ViewTabItem } from "@/components/layout/ViewTabs";
import { PageHeader } from "@/components/PageHeader";
import { WorkingLocationBar } from "@/components/scan/WorkingLocationBar";
import { Button } from "@/components/ui/Button";
import { CreateWorkItemForm, type WorkItemContextOption } from "@/components/work-items/CreateWorkItemForm";
import { ShiftHandoverPanel } from "@/components/work-items/ShiftHandoverPanel";
import { computeHomeKpis } from "@/lib/format/homeKpis";
import {
  segmentForAttention,
  segmentForCarryover,
  segmentForMine,
  segmentForReady,
  segmentsTotalCount,
  type HomeQueueSegment,
  type HomeQueueSources,
} from "@/lib/format/homeQueue";
import { humanizeEnumCode } from "@/lib/format/humanize";
import { flattenLocationTree } from "@/lib/format/locationTree";
import { groupBatchesByStage } from "@/lib/format/stageOrder";
import { bucketWorkItems } from "@/lib/format/workItemBoard";
import { useViewState } from "@/lib/navigation/useViewState";
import {
  useAssets,
  useCarriers,
  useCropIssues,
  useCurrentUserId,
  useEquipmentAttention,
  useEquipmentIncidents,
  useFarm,
  useFarmProtocolDueSummary,
  useHarvestablePlates,
  useLatestShiftHandover,
  useLocationsTree,
  useOperationalSummary,
  useWaterAttention,
  useWorkItems,
} from "@/lib/query/hooks";
import { useWorkingLocation } from "@/lib/scan/useWorkingLocation";

const HOME_VIEWS = ["mine", "ready", "attention", "carryover", "overview"] as const;
type HomeView = (typeof HOME_VIEWS)[number];

const VIEW_LABELS: Record<HomeView, string> = {
  mine: "Mine",
  ready: "Ready",
  attention: "Attention",
  carryover: "Carryover",
  overview: "Overview",
};

function SummaryCard({ label, value, href, caption }: { label: string; value: string | number; href?: string; caption?: string }) {
  const cardClass = `h-full rounded-xl border border-wl-border bg-wl-surface-raised p-4 transition-colors ${href ? "hover:border-wl-brand" : ""}`;
  const content = (
    <div className={cardClass}>
      <p className="text-xs font-semibold uppercase tracking-wide text-wl-text-secondary">{label}</p>
      <p className="mt-1 font-serif text-2xl font-semibold text-wl-text">{value}</p>
      {caption && <p className="mt-0.5 text-xs text-wl-text-secondary">{caption}</p>}
    </div>
  );
  return href ? (
    <Link
      href={href}
      className="block rounded-xl focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-wl-focus"
    >
      {content}
    </Link>
  ) : (
    content
  );
}

/** Compact operational-context stat -- always visible outside the current
 * view's own queue (ticket §5.3: "Keep compact In Progress, Blocked, and
 * Carryover counts visible outside the view-specific queue"). `onOpen`,
 * when given, switches the active durable view to that stat's own queue.
 * UX-OPS-001B R1: `count === undefined` (the Work Item source failed or is
 * still loading) renders "—", never a false `0` -- a stat derived from a
 * failed source must read as unavailable, not as "nothing here". */
function ContextStat({ label, count, onOpen }: { label: string; count: number | undefined; onOpen?: () => void }) {
  const content = (
    <>
      <span className="text-xs font-medium text-wl-text-secondary">{label}</span>
      <span className="font-serif text-lg font-semibold text-wl-text">{count ?? "—"}</span>
    </>
  );
  if (onOpen) {
    return (
      <button
        type="button"
        onClick={onOpen}
        className="flex min-h-11 flex-col items-start gap-0.5 rounded-lg px-2.5 py-1 text-left hover:bg-wl-surface-hover focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-wl-focus"
      >
        {content}
      </button>
    );
  }
  return <div className="flex flex-col gap-0.5 px-2.5 py-1">{content}</div>;
}

export default function FarmHomePage() {
  const { farmId } = useParams<{ farmId: string }>();
  const currentUserId = useCurrentUserId();
  const { data: farm } = useFarm(farmId);
  const { view, selected, setView, setSelected } = useViewState<HomeView>({ views: HOME_VIEWS, defaultView: "mine" });

  const workItemsQuery = useWorkItems(farmId);
  const handoverQuery = useLatestShiftHandover(farmId);
  const harvestableQuery = useHarvestablePlates(farmId);
  const summaryQuery = useOperationalSummary(farmId, "active");
  const cropIssuesQuery = useCropIssues(farmId);
  const protocolDueQuery = useFarmProtocolDueSummary(farmId);
  const waterAttentionQuery = useWaterAttention(farmId);
  const equipmentAttentionQuery = useEquipmentAttention(farmId);
  const locationsTreeQuery = useLocationsTree(farmId);
  const assetsQuery = useAssets(farmId, "");
  const carriersQuery = useCarriers(farmId);
  const openEquipmentIncidentsQuery = useEquipmentIncidents(farmId, {
    status: ["open", "acknowledged", "action_in_progress"],
  });

  const [creating, setCreating] = useState(false);
  const { workingLocation, clearWorkingLocation } = useWorkingLocation();

  const locationOptions: WorkItemContextOption[] = useMemo(
    () => flattenLocationTree(locationsTreeQuery.data ?? []).map((o) => ({ id: o.id, label: o.label })),
    [locationsTreeQuery.data],
  );
  const batchOptions: WorkItemContextOption[] = useMemo(
    () => (summaryQuery.data ?? []).map((b) => ({ id: b.id, label: `${b.code} · ${b.crop.common_name}` })),
    [summaryQuery.data],
  );
  const assetOptions: WorkItemContextOption[] = useMemo(
    () => (assetsQuery.data ?? []).map((a) => ({ id: a.id, label: `${a.name} (${a.code})` })),
    [assetsQuery.data],
  );
  const carrierOptions: WorkItemContextOption[] = useMemo(
    () => (carriersQuery.data ?? []).map((c) => ({ id: c.id, label: c.code })),
    [carriersQuery.data],
  );
  const equipmentIncidentOptions: WorkItemContextOption[] = useMemo(
    () => (openEquipmentIncidentsQuery.data ?? []).map((i) => ({ id: i.id, label: `${i.code} · ${i.asset?.code ?? "—"}` })),
    [openEquipmentIncidentsQuery.data],
  );

  const board = useMemo(
    () =>
      bucketWorkItems(workItemsQuery.data ?? [], {
        currentUserId,
        now: new Date(),
        farmTimezone: farm?.timezone ?? "UTC",
      }),
    [workItemsQuery.data, currentUserId, farm?.timezone],
  );

  const activeBatches = summaryQuery.data ?? [];
  const homeKpis = computeHomeKpis(activeBatches);
  const stageBreakdown = useMemo(() => (summaryQuery.data ? groupBatchesByStage(summaryQuery.data) : []), [summaryQuery.data]);
  const stageNameOccurrences = useMemo(() => {
    const counts = new Map<string, number>();
    for (const group of stageBreakdown) counts.set(group.name, (counts.get(group.name) ?? 0) + 1);
    return counts;
  }, [stageBreakdown]);

  const queueSources: HomeQueueSources = useMemo(
    () => ({
      myWorkItems: { data: board.myWork, isLoading: workItemsQuery.isLoading, error: workItemsQuery.error },
      harvestablePlates: { data: harvestableQuery.data, isLoading: harvestableQuery.isLoading, error: harvestableQuery.error },
      activeBatches: { data: summaryQuery.data, isLoading: summaryQuery.isLoading, error: summaryQuery.error },
      cropIssues: { data: cropIssuesQuery.data, isLoading: cropIssuesQuery.isLoading, error: cropIssuesQuery.error },
      inspectionsDue: { data: protocolDueQuery.data, isLoading: protocolDueQuery.isLoading, error: protocolDueQuery.error },
      waterAttention: { data: waterAttentionQuery.data, isLoading: waterAttentionQuery.isLoading, error: waterAttentionQuery.error },
      equipmentAttention: {
        data: equipmentAttentionQuery.data,
        isLoading: equipmentAttentionQuery.isLoading,
        error: equipmentAttentionQuery.error,
      },
      blockedWorkItems: { data: board.blocked, isLoading: workItemsQuery.isLoading, error: workItemsQuery.error },
      carryoverWorkItems: { data: board.carryover, isLoading: workItemsQuery.isLoading, error: workItemsQuery.error },
    }),
    [
      board,
      workItemsQuery.isLoading,
      workItemsQuery.error,
      harvestableQuery.data,
      harvestableQuery.isLoading,
      harvestableQuery.error,
      summaryQuery.data,
      summaryQuery.isLoading,
      summaryQuery.error,
      cropIssuesQuery.data,
      cropIssuesQuery.isLoading,
      cropIssuesQuery.error,
      protocolDueQuery.data,
      protocolDueQuery.isLoading,
      protocolDueQuery.error,
      waterAttentionQuery.data,
      waterAttentionQuery.isLoading,
      waterAttentionQuery.error,
      equipmentAttentionQuery.data,
      equipmentAttentionQuery.isLoading,
      equipmentAttentionQuery.error,
    ],
  );

  const mineSegments = useMemo(() => segmentForMine(queueSources), [queueSources]);
  const readySegments = useMemo(() => segmentForReady(queueSources), [queueSources]);
  const attentionSegments = useMemo(() => segmentForAttention(queueSources), [queueSources]);
  const carryoverSegments = useMemo(() => segmentForCarryover(queueSources), [queueSources]);

  const segmentsByView: Record<Exclude<HomeView, "overview">, HomeQueueSegment[]> = useMemo(
    () => ({ mine: mineSegments, ready: readySegments, attention: attentionSegments, carryover: carryoverSegments }),
    [mineSegments, readySegments, attentionSegments, carryoverSegments],
  );

  const activeSegments = useMemo(() => (view === "overview" ? [] : segmentsByView[view]), [view, segmentsByView]);
  const selectedRow = useMemo(
    () => (selected ? activeSegments.flatMap((s) => s.rows).find((r) => r.id === selected) ?? null : null),
    [activeSegments, selected],
  );

  const retryBySegmentKey: Record<string, () => void> = {
    "mine-work-items": () => workItemsQuery.refetch(),
    "ready-harvest": () => harvestableQuery.refetch(),
    "attention-quality-holds": () => summaryQuery.refetch(),
    "attention-crop-issues": () => cropIssuesQuery.refetch(),
    "attention-inspections-due": () => protocolDueQuery.refetch(),
    "attention-water": () => waterAttentionQuery.refetch(),
    "attention-equipment": () => equipmentAttentionQuery.refetch(),
    "attention-blocked-work-items": () => workItemsQuery.refetch(),
    "carryover-work-items": () => workItemsQuery.refetch(),
  };

  const viewTabs: ViewTabItem<HomeView>[] = HOME_VIEWS.map((v) => ({
    value: v,
    label: VIEW_LABELS[v],
    count: v === "overview" ? undefined : segmentsTotalCount(segmentsByView[v]),
  }));

  return (
    <div>
      <PageHeader
        title="Today on the Farm"
        description={farm ? farm.name : undefined}
        compact
        actions={
          !creating && (
            <div className="flex flex-wrap items-center gap-2">
              <Link
                href="/scan"
                className="flex h-9 items-center gap-1.5 rounded-lg border border-wl-border-strong bg-wl-surface-raised px-4 text-sm font-medium text-wl-text hover:bg-wl-surface-hover focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-wl-focus"
              >
                Scan / Enter QR
              </Link>
              <Button variant="primary" onClick={() => setCreating(true)}>
                New work item
              </Button>
            </div>
          )
        }
      />

      {workingLocation && (
        <div className="mb-4">
          <WorkingLocationBar workingLocation={workingLocation} onClear={clearWorkingLocation} scanLinkLabel="Scan next" />
        </div>
      )}

      {creating && (
        <div className="mb-6">
          <CreateWorkItemForm
            farmId={farmId}
            currentUserId={currentUserId}
            locationOptions={locationOptions}
            batchOptions={batchOptions}
            assetOptions={assetOptions}
            carrierOptions={carrierOptions}
            equipmentIncidentOptions={equipmentIncidentOptions}
            onCancel={() => setCreating(false)}
            onSuccess={() => setCreating(false)}
          />
        </div>
      )}

      <div className="mb-4">
        <ShiftHandoverPanel farmId={farmId} latest={handoverQuery.data} openWorkItems={board.farmWide} />
      </div>

      <div
        aria-label="Operational context"
        className="mb-4 flex flex-wrap items-center gap-1 rounded-xl border border-wl-border bg-wl-surface-raised px-1 py-1"
      >
        <ContextStat
          label="In Progress"
          count={workItemsQuery.isLoading || workItemsQuery.error ? undefined : board.inProgress.length}
        />
        <ContextStat
          label="Blocked"
          count={workItemsQuery.isLoading || workItemsQuery.error ? undefined : board.blocked.length}
          onOpen={() => setView("attention")}
        />
        <ContextStat
          label="Carryover"
          count={workItemsQuery.isLoading || workItemsQuery.error ? undefined : board.carryover.length}
          onOpen={() => setView("carryover")}
        />
      </div>

      <div className="mb-4">
        <ViewTabs items={viewTabs} active={view} onChange={setView} />
      </div>

      {view === "overview" ? (
        <section>
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-3">
            <SummaryCard label="Active batches" value={homeKpis.activeCount} href={`/farms/${farmId}/crop-batches`} />
            <SummaryCard
              label="Harvest ready"
              value={homeKpis.harvestReadyCount}
              href={`/farms/${farmId}/crop-batches?filter=harvest_ready`}
            />
            <SummaryCard
              label="Batches with open quality holds"
              value={homeKpis.openHoldBatchCount}
              href={`/farms/${farmId}/crop-batches?filter=quality_hold`}
              caption={homeKpis.openHoldBatchCount === 1 ? "1 batch affected" : `${homeKpis.openHoldBatchCount} batches affected`}
            />
          </div>

          {stageBreakdown.length > 0 && (
            <BoundedDataRegion label="Production by stage">
              <ul className="divide-y divide-wl-border">
                {stageBreakdown.map((stage) => {
                  const needsDisambiguation = (stageNameOccurrences.get(stage.name) ?? 0) > 1;
                  return (
                    <li key={`${stage.category}-${stage.name}`} className="flex items-center justify-between gap-3 px-3.5 py-2 text-sm">
                      <span className="text-wl-text">
                        {stage.name}
                        {needsDisambiguation && <span className="text-wl-text-secondary"> · {humanizeEnumCode(stage.category)}</span>}
                      </span>
                      <span className="inline-flex min-w-8 shrink-0 items-center justify-center rounded-full bg-wl-brand-subtle px-2 py-0.5 text-xs font-semibold text-wl-brand">
                        {stage.count}
                      </span>
                    </li>
                  );
                })}
              </ul>
            </BoundedDataRegion>
          )}
        </section>
      ) : (
        <SplitWorkspace
          main={
            <HomeQueueView
              segments={activeSegments}
              selectedId={selected}
              onSelect={(id) => setSelected(id)}
              onRetry={(key) => retryBySegmentKey[key]?.()}
            />
          }
          rail={
            selectedRow ? (
              <HomeInspector row={selectedRow} farmId={farmId} currentUserId={currentUserId} onClose={() => setSelected(null)} />
            ) : (
              <InspectorEmptyState />
            )
          }
        />
      )}
    </div>
  );
}
