"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useMemo, useState } from "react";

import { ErrorState } from "@/components/ErrorState";
import { LoadingSkeleton } from "@/components/LoadingSkeleton";
import { PageHeader } from "@/components/PageHeader";
import { WorkingLocationBar } from "@/components/scan/WorkingLocationBar";
import { Button } from "@/components/ui/Button";
import { CreateWorkItemForm, type WorkItemContextOption } from "@/components/work-items/CreateWorkItemForm";
import { ShiftHandoverPanel } from "@/components/work-items/ShiftHandoverPanel";
import { WorkItemSection } from "@/components/work-items/WorkItemSection";
import type { FarmWorkItemCreate } from "@/lib/api/client";
import { AppError } from "@/lib/errors/adapter";
import { computeHomeKpis } from "@/lib/format/homeKpis";
import { humanizeEnumCode } from "@/lib/format/humanize";
import { flattenLocationTree } from "@/lib/format/locationTree";
import { groupBatchesByStage } from "@/lib/format/stageOrder";
import { bucketWorkItems } from "@/lib/format/workItemBoard";
import {
  useAssets,
  useCarriers,
  useCreateWorkItem,
  useCropIssues,
  useCurrentUserId,
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

function errorMessage(error: unknown): string {
  return error instanceof AppError ? error.message : "Something went wrong. Please try again.";
}

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

/** A failed LIVE aggregation source (Ready Now / Attention) must never be
 * silently rendered as "nothing to do" -- shows its own retry-able error
 * inline, independent of every other section on the board (CLAUDE.md
 * "Empty / Error / Loading truth"). */
function LiveSourcePanel({
  title,
  isLoading,
  error,
  onRetry,
  isEmpty,
  emptyLabel,
  children,
}: {
  title: string;
  isLoading: boolean;
  error: unknown;
  onRetry: () => void;
  isEmpty: boolean;
  emptyLabel: string;
  children: React.ReactNode;
}) {
  return (
    <section className="mt-6">
      <h2 className="mb-2 font-serif text-base font-semibold text-wl-text">{title}</h2>
      {isLoading && <LoadingSkeleton rows={2} label={`Loading ${title.toLowerCase()}`} />}
      {!isLoading && Boolean(error) && <ErrorState error={error} onRetry={onRetry} />}
      {!isLoading && !error && isEmpty && <p className="text-sm text-wl-text-secondary">{emptyLabel}</p>}
      {!isLoading && !error && !isEmpty && children}
    </section>
  );
}

export default function FarmHomePage() {
  const { farmId } = useParams<{ farmId: string }>();
  const currentUserId = useCurrentUserId();
  const { data: farm } = useFarm(farmId);

  const workItemsQuery = useWorkItems(farmId);
  const handoverQuery = useLatestShiftHandover(farmId);
  const harvestableQuery = useHarvestablePlates(farmId);
  const summaryQuery = useOperationalSummary(farmId, "active");
  // PILOT-AGRO-001B Part 8: live agronomy readiness -- computed/read-model,
  // never a persisted duplicate of a Farm Work Item (an "Inspection due"
  // row here is never itself written to farm_work_items; only explicit
  // corrective work assigned from a Crop Issue is).
  const cropIssuesQuery = useCropIssues(farmId);
  const protocolDueQuery = useFarmProtocolDueSummary(farmId);
  const waterAttentionQuery = useWaterAttention(farmId);
  // PILOT-OPS-001 closure: structured context option sources for manual
  // Work Item creation -- each reuses an existing farm-scoped read
  // (Locations tree, Batch summary already fetched above, Assets,
  // Carriers), never a new picker or a new endpoint.
  const locationsTreeQuery = useLocationsTree(farmId);
  const assetsQuery = useAssets(farmId, "");
  const carriersQuery = useCarriers(farmId);

  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);
  const createMutation = useCreateWorkItem(farmId);
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

  const board = useMemo(
    () =>
      bucketWorkItems(workItemsQuery.data ?? [], {
        currentUserId,
        now: new Date(),
        farmTimezone: farm?.timezone ?? "UTC",
      }),
    [workItemsQuery.data, currentUserId, farm?.timezone],
  );

  const attentionBatches = useMemo(
    () => (summaryQuery.data ?? []).filter((b) => b.open_quality_hold_count > 0),
    [summaryQuery.data],
  );

  const activeBatches = summaryQuery.data ?? [];
  const homeKpis = computeHomeKpis(activeBatches);
  const stageBreakdown = useMemo(
    () => (summaryQuery.data ? groupBatchesByStage(summaryQuery.data) : []),
    [summaryQuery.data],
  );
  const stageNameOccurrences = useMemo(() => {
    const counts = new Map<string, number>();
    for (const group of stageBreakdown) counts.set(group.name, (counts.get(group.name) ?? 0) + 1);
    return counts;
  }, [stageBreakdown]);

  function handleCreate(payload: FarmWorkItemCreate) {
    setCreateError(null);
    createMutation.mutate(payload, {
      onSuccess: () => setCreating(false),
      onError: (error) => setCreateError(errorMessage(error)),
    });
  }

  if (workItemsQuery.isLoading) {
    return <LoadingSkeleton rows={4} label="Loading today on the farm" />;
  }
  if (workItemsQuery.error) {
    return <ErrorState error={workItemsQuery.error} onRetry={() => workItemsQuery.refetch()} />;
  }

  return (
    <div>
      <PageHeader
        title="Today on the Farm"
        description={farm ? farm.name : undefined}
        actions={
          !creating && (
            <div className="flex flex-wrap items-center gap-2">
              {/* PILOT-SCAN-001E: a compact fallback for an operator whose
                  device camera can't read a damaged/dirty label -- the
                  physical QR itself already opens `/q/{token}` directly via
                  the device's own native camera app, so this deliberately
                  stays small and secondary next to "New work item", never a
                  dominant feature of this page. */}
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

      {/* PILOT-SCAN-001F: low-cost indicator only -- no dashboard, no new
          section of the page's own logic; identical component to /q and
          /scan, reused rather than duplicated. */}
      {workingLocation && (
        <div className="mb-4">
          <WorkingLocationBar workingLocation={workingLocation} onClear={clearWorkingLocation} scanLinkLabel="Scan next" />
        </div>
      )}

      {creating && (
        <div className="mb-6">
          <CreateWorkItemForm
            isSubmitting={createMutation.isPending}
            serverError={createError}
            currentUserId={currentUserId}
            locationOptions={locationOptions}
            batchOptions={batchOptions}
            assetOptions={assetOptions}
            carrierOptions={carrierOptions}
            onCancel={() => {
              setCreating(false);
              setCreateError(null);
            }}
            onSubmit={handleCreate}
          />
        </div>
      )}

      <ShiftHandoverPanel farmId={farmId} latest={handoverQuery.data} openWorkItems={board.farmWide} />

      <WorkItemSection title="My Work" items={board.myWork} farmId={farmId} currentUserId={currentUserId} emptyLabel="Nothing assigned to you right now." />

      <LiveSourcePanel
        title="Ready Now"
        isLoading={harvestableQuery.isLoading}
        error={harvestableQuery.error}
        onRetry={() => harvestableQuery.refetch()}
        isEmpty={(harvestableQuery.data ?? []).length === 0}
        emptyLabel="Nothing ready to harvest right now."
      >
        <ul className="divide-y divide-wl-border rounded-xl border border-wl-border bg-wl-surface-raised">
          {(harvestableQuery.data ?? []).map((plate) => (
            <li key={plate.production_plate_id} className="flex items-center justify-between gap-3 px-4 py-2.5 text-sm">
              <span className="text-wl-text">
                {plate.crop_common_name} · Batch {plate.batch_code} · {plate.production_plate_code}
                {plate.location?.grow_table && (
                  <span className="text-wl-text-secondary"> · {plate.location.grow_table.code}</span>
                )}
              </span>
              <Link
                href={`/farms/${farmId}/leafy-production/harvest?batchId=${plate.batch_id}`}
                className="shrink-0 text-sm font-medium text-wl-brand hover:underline"
              >
                Open Harvest
              </Link>
            </li>
          ))}
        </ul>
      </LiveSourcePanel>

      <LiveSourcePanel
        title="Attention"
        isLoading={summaryQuery.isLoading}
        error={summaryQuery.error}
        onRetry={() => summaryQuery.refetch()}
        isEmpty={attentionBatches.length === 0}
        emptyLabel="No exceptions right now."
      >
        <ul className="divide-y divide-wl-border rounded-xl border border-wl-border bg-wl-surface-raised">
          {attentionBatches.map((b) => (
            <li key={b.id} className="flex items-center justify-between gap-3 px-4 py-2.5 text-sm">
              <span className="text-wl-text">
                Batch {b.code} · {b.open_quality_hold_count} open quality hold{b.open_quality_hold_count === 1 ? "" : "s"}
              </span>
              <Link href={`/farms/${farmId}/crop-batches/${b.id}`} className="shrink-0 text-sm font-medium text-wl-brand hover:underline">
                View batch
              </Link>
            </li>
          ))}
        </ul>
      </LiveSourcePanel>

      <LiveSourcePanel
        title="Crop Attention"
        isLoading={cropIssuesQuery.isLoading}
        error={cropIssuesQuery.error}
        onRetry={() => cropIssuesQuery.refetch()}
        isEmpty={(cropIssuesQuery.data ?? []).filter((i) => i.status === "open").length === 0}
        emptyLabel="No open crop issues right now."
      >
        <ul className="divide-y divide-wl-border rounded-xl border border-wl-border bg-wl-surface-raised">
          {(cropIssuesQuery.data ?? [])
            .filter((i) => i.status === "open")
            .map((issue) => (
              <li key={issue.id} className="flex items-center justify-between gap-3 px-4 py-2.5 text-sm">
                <span className="text-wl-text">
                  {issue.code} · {humanizeEnumCode(issue.category)} · {humanizeEnumCode(issue.severity)}
                  {issue.is_follow_up_overdue && <span className="text-wl-flag-fg"> · follow-up overdue</span>}
                </span>
                <Link href={`/farms/${farmId}/crop-issues/${issue.id}`} className="shrink-0 text-sm font-medium text-wl-brand hover:underline">
                  Open issue
                </Link>
              </li>
            ))}
        </ul>
      </LiveSourcePanel>

      <LiveSourcePanel
        title="Inspections Due"
        isLoading={protocolDueQuery.isLoading}
        error={protocolDueQuery.error}
        onRetry={() => protocolDueQuery.refetch()}
        isEmpty={(protocolDueQuery.data ?? []).length === 0}
        emptyLabel="No inspections due right now."
      >
        <ul className="divide-y divide-wl-border rounded-xl border border-wl-border bg-wl-surface-raised">
          {(protocolDueQuery.data ?? []).map((row) => (
            <li key={row.batch_id} className="flex items-center justify-between gap-3 px-4 py-2.5 text-sm">
              <span className="text-wl-text">
                Batch {row.batch_code} · {row.protocol?.name}
                {row.overdue_count > 0 ? (
                  <span className="text-wl-flag-fg"> · {row.overdue_count} overdue</span>
                ) : (
                  <span className="text-wl-text-secondary"> · {row.due_count} due</span>
                )}
              </span>
              <Link href={`/farms/${farmId}/production/inspect?batchId=${row.batch_id}`} className="shrink-0 text-sm font-medium text-wl-brand hover:underline">
                Inspect Crop
              </Link>
            </li>
          ))}
        </ul>
      </LiveSourcePanel>

      <LiveSourcePanel
        title="Water Attention"
        isLoading={waterAttentionQuery.isLoading}
        error={waterAttentionQuery.error}
        onRetry={() => waterAttentionQuery.refetch()}
        isEmpty={(waterAttentionQuery.data ?? []).length === 0}
        emptyLabel="Nothing currently needs Water attention."
      >
        <ul className="divide-y divide-wl-border rounded-xl border border-wl-border bg-wl-surface-raised">
          {(waterAttentionQuery.data ?? []).map((item, i) => (
            <li key={`${item.kind}-${i}`} className="flex items-center justify-between gap-3 px-4 py-2.5 text-sm">
              <span className="text-wl-text">{item.message}</span>
              <Link
                href={item.kind === "CIRCUIT_MISSING_RESERVOIR" ? `/farms/${farmId}/water/setup` : `/farms/${farmId}/water/measurements`}
                className="shrink-0 text-sm font-medium text-wl-brand hover:underline"
              >
                Open Water &amp; Nutrients
              </Link>
            </li>
          ))}
        </ul>
      </LiveSourcePanel>

      <WorkItemSection title="In Progress" items={board.inProgress} farmId={farmId} currentUserId={currentUserId} hideWhenEmpty />
      <WorkItemSection title="Blocked" items={board.blocked} farmId={farmId} currentUserId={currentUserId} hideWhenEmpty />
      <WorkItemSection
        title="Carryover"
        items={board.carryover}
        farmId={farmId}
        currentUserId={currentUserId}
        hideWhenEmpty
      />
      <WorkItemSection
        title="Farm Work"
        items={board.farmWide}
        farmId={farmId}
        currentUserId={currentUserId}
        emptyLabel="No open work items for this farm."
      />

      {/* Secondary, below the operational work engine -- PILOT-UX-003's
          deep-linking KPIs, unchanged, never the page's primary content. */}
      {!summaryQuery.isLoading && !summaryQuery.error && (
        <section className="mt-8 border-t border-wl-border pt-6">
          <h2 className="mb-3 font-serif text-base font-semibold text-wl-text">Production overview</h2>
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
            <ul className="mt-4 divide-y divide-wl-border rounded-xl border border-wl-border bg-wl-surface-raised">
              {stageBreakdown.map((stage) => {
                const needsDisambiguation = (stageNameOccurrences.get(stage.name) ?? 0) > 1;
                return (
                  <li key={`${stage.category}-${stage.name}`} className="flex items-center justify-between gap-3 px-4 py-2.5 text-sm">
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
          )}
        </section>
      )}
    </div>
  );
}
