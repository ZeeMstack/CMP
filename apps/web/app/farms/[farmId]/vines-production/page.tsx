"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";

import { Breadcrumbs } from "@/components/Breadcrumbs";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { LoadingSkeleton } from "@/components/LoadingSkeleton";
import { PageHeader } from "@/components/PageHeader";
import { StatusBadge } from "@/components/StatusBadge";
import { BoundedDataRegion } from "@/components/layout/BoundedDataRegion";
import { InspectorEmptyState, InspectorShell } from "@/components/layout/InspectorShell";
import { QueueList, QueueRow } from "@/components/layout/QueueRow";
import { SplitWorkspace } from "@/components/layout/SplitWorkspace";
import { RecordGrowCubeLossForm } from "@/components/vines/RecordGrowCubeLossForm";
import { VinesLossHistoryPanel } from "@/components/vines/VinesLossHistoryPanel";
import { Button } from "@/components/ui/Button";
import { Tabs } from "@/components/ui/Tabs";
import type { VinesProductionPlacementGrowBagRead, VinesProductionPlacementRead } from "@/lib/api/client";
import { AppError } from "@/lib/errors/adapter";
import { vinesGroupActions, vinesGrowBagActions } from "@/lib/format/productionActions";
import {
  useCorrectVinesGrowCubeDisposition,
  useRecordVinesGrowCubeDisposition,
  useVinesProductionDispositionHistory,
  useVinesProductionPlacementGrowBags,
  useVinesProductionPlacements,
} from "@/lib/query/hooks";

const TABS = [
  { id: "population", label: "Population" },
  { id: "history", label: "Loss History" },
] as const;

function groupKey(row: Pick<VinesProductionPlacementRead, "batch_id" | "gutter_id">): string {
  return `${row.batch_id}:${row.gutter_id}`;
}

function asAppError(error: unknown): AppError {
  return error instanceof AppError ? error : new AppError("server_error", "Something went wrong. Please try again.");
}

/** VINES-OPS-001B/VINES-OPS-002: the real Vines Production operational
 * workspace -- "Population" (compact aggregated Batch/Gutter rows, drill
 * down to Grow Bag/Grow Cube, Record Plant Loss inline) and "Loss History"
 * (correction). Mirrors `leafy-production/page.tsx`'s own established
 * two-section shape for the sibling authority. The 001B Transfer workflow
 * remains its own separate nav entry (`vines-production/transfer`),
 * untouched.
 *
 * UX-OPS-001C: "Population" is a bounded (Batch, Gutter) work queue plus a
 * stable selected-row inspector holding that group's Grow Bags; per-bag
 * actions come from `vinesGrowBagActions` (no Move -- no Vines relocation
 * command exists). */
export default function VinesProductionPage() {
  const { farmId } = useParams<{ farmId: string }>();
  const [tab, setTab] = useState<"population" | "history">("population");
  const [selectedKey, setSelectedKey] = useState<string | null>(null);

  const placementsQuery = useVinesProductionPlacements(farmId);
  const placements = placementsQuery.data ?? [];
  const selectedGroup = placements.find((row) => groupKey(row) === selectedKey) ?? null;
  const historyQuery = useVinesProductionDispositionHistory(farmId);
  const correctMutation = useCorrectVinesGrowCubeDisposition(farmId);
  const [correctingEventId, setCorrectingEventId] = useState<string | null>(null);
  const [correctError, setCorrectError] = useState<AppError | null>(null);
  // UX-OPS-001C/R1: true while a loss or void form holds an in-flight or
  // unresolved attempt -- tabs and row selection would unmount it and lose
  // its frozen Retry, so both are locked until it resolves.
  const [commandLocked, setCommandLocked] = useState(false);

  return (
    <div>
      <PageHeader
        compact
        title="Vines Production"
        breadcrumbs={
          <Breadcrumbs
            items={[
              { label: "Home", href: `/farms/${farmId}` },
              { label: "Vines Production" },
            ]}
          />
        }
      />

      <div className="mb-4">
        <Tabs
          tabs={TABS.map(({ id, label }) => ({ id, label }))}
          activeId={tab}
          onChange={(id) => {
            if (!commandLocked) setTab(id as "population" | "history");
          }}
          aria-label="Vines Production sections"
        />
      </div>

      {tab === "population" && (
        <>
          {placementsQuery.isLoading && <LoadingSkeleton rows={4} label="Loading Vines Production placements" />}
          {placementsQuery.isError && (
            <ErrorState error={placementsQuery.error} onRetry={() => placementsQuery.refetch()} />
          )}
          {placementsQuery.isSuccess && placements.length === 0 && (
            <EmptyState
              title="Nothing is currently in Vines Production."
              description="Plants appear here once a Transfer to Production has placed living plants in a Grow Gutter."
            />
          )}
          {placementsQuery.isSuccess && placements.length > 0 && (
            <SplitWorkspace
              main={
                <BoundedDataRegion
                  label="Vines Production population"
                  heading={
                    <div className="flex justify-between text-xs font-medium text-wl-text-secondary">
                      <span>Batch · Gutter · Crop</span>
                      <span>Living · Lost · Days</span>
                    </div>
                  }
                >
                  <QueueList label="Vines Production population">
                    {placements.map((row) => {
                      const key = groupKey(row);
                      return (
                        <QueueRow
                          key={key}
                          isSelected={key === selectedKey}
                          onSelect={() => {
                            if (!commandLocked) setSelectedKey(key);
                          }}
                          title={`${row.batch_code} · ${row.gutter_code}`}
                          context={`${row.crop_common_name}${row.variety_name ? ` / ${row.variety_name}` : ""} · ${row.greenhouse_code}`}
                          status={row.lost_plant_count > 0 ? <StatusBadge label={`Lost ${row.lost_plant_count.toLocaleString()}`} tone="attention" /> : undefined}
                          meta={
                            <span className="flex flex-col items-end">
                              <span className="text-sm font-semibold tabular-nums text-wl-text">
                                {row.living_plant_count.toLocaleString()}
                              </span>
                              <span>Day {row.days_in_production}</span>
                            </span>
                          }
                        />
                      );
                    })}
                  </QueueList>
                </BoundedDataRegion>
              }
              rail={
                selectedGroup ? (
                  <InspectorShell
                    // Re-keyed per group so a half-finished Record Loss form
                    // for one Gutter is never carried into another.
                    key={groupKey(selectedGroup)}
                    title={`${selectedGroup.batch_code} · ${selectedGroup.gutter_code}`}
                    subtitle={`${selectedGroup.crop_common_name}${selectedGroup.variety_name ? ` / ${selectedGroup.variety_name}` : ""} · ${selectedGroup.greenhouse_code}`}
                    onClose={commandLocked ? undefined : () => setSelectedKey(null)}
                  >
                    <dl className="grid grid-cols-3 gap-x-4 gap-y-2 text-sm">
                      <div>
                        <dt className="text-xs text-wl-text-secondary">Living</dt>
                        <dd className="text-xl font-semibold tabular-nums text-wl-text">
                          {selectedGroup.living_plant_count.toLocaleString()}
                        </dd>
                      </div>
                      <div>
                        <dt className="text-xs text-wl-text-secondary">Lost</dt>
                        <dd className="tabular-nums text-wl-text">{selectedGroup.lost_plant_count.toLocaleString()}</dd>
                      </div>
                      <div>
                        <dt className="text-xs text-wl-text-secondary">Days in Production</dt>
                        <dd className="tabular-nums text-wl-text">{selectedGroup.days_in_production}</dd>
                      </div>
                    </dl>
                    {vinesGroupActions(farmId, selectedGroup.batch_id, selectedGroup.living_plant_count).length > 0 && (
                      <div className="flex flex-wrap gap-x-4 gap-y-2">
                        {vinesGroupActions(farmId, selectedGroup.batch_id, selectedGroup.living_plant_count).map((action) => (
                          <Link
                            key={action.kind}
                            href={action.href as string}
                            className="inline-flex min-h-9 items-center text-sm font-medium text-wl-brand hover:underline"
                          >
                            {action.label}
                          </Link>
                        ))}
                      </div>
                    )}
                    <div className="border-t border-wl-border pt-3">
                      <h3 className="mb-2 text-xs font-medium uppercase tracking-wide text-wl-text-secondary">Grow Bags</h3>
                      <GrowBagDrillDown
                        farmId={farmId}
                        batchId={selectedGroup.batch_id}
                        gutterId={selectedGroup.gutter_id}
                        onCommandLockedChange={setCommandLocked}
                      />
                    </div>
                  </InspectorShell>
                ) : (
                  <InspectorEmptyState
                    label={
                      selectedKey
                        ? "This Gutter no longer has living plants of that Batch. Select another row."
                        : "Select a Batch / Gutter to see its Grow Bags and actions."
                    }
                  />
                )
              }
            />
          )}
        </>
      )}

      {tab === "history" && (
        <VinesLossHistoryPanel
          lineages={historyQuery.data ?? []}
          // Backend enforces BIOLOGICAL_DISPOSITION_CORRECT authoritatively --
          // mirrors PlantLossHistoryPanel's own established rationale.
          canCorrect={true}
          onCommandLockedChange={setCommandLocked}
          correctingEventId={correctingEventId}
          isSubmitting={correctMutation.isPending}
          serverError={correctError}
          onCorrect={async (eventId: string, payload) => {
            setCorrectingEventId(eventId);
            setCorrectError(null);
            try {
              await correctMutation.mutateAsync({ eventId, payload });
            } catch (error) {
              const appError = asAppError(error);
              setCorrectError(appError);
              throw appError;
            } finally {
              setCorrectingEventId(null);
            }
          }}
        />
      )}
    </div>
  );
}

function GrowBagDrillDown({
  farmId,
  batchId,
  gutterId,
  onCommandLockedChange,
}: {
  farmId: string;
  batchId: string;
  gutterId: string;
  onCommandLockedChange: (locked: boolean) => void;
}) {
  const detailQuery = useVinesProductionPlacementGrowBags(farmId, batchId, gutterId);
  const recordMutation = useRecordVinesGrowCubeDisposition(farmId);
  const [lossTargetBagId, setLossTargetBagId] = useState<string | null>(null);
  const [recordError, setRecordError] = useState<AppError | null>(null);
  const [recordSuccess, setRecordSuccess] = useState<{ bagCode: string; resulting: number; released: boolean } | null>(null);

  if (detailQuery.isLoading) return <p className="text-xs text-ink-muted">Loading Grow Bags…</p>;
  const bags = detailQuery.data ?? [];
  const lossTargetBag: VinesProductionPlacementGrowBagRead | null =
    bags.find((b) => b.batch_carrier_assignment_id === lossTargetBagId) ?? null;

  if (recordSuccess) {
    return (
      <div className="flex flex-col gap-3 rounded-md border border-border-subtle bg-surface p-3 text-sm">
        <h3 className="font-serif text-sm font-semibold text-ink">Plant loss recorded — {recordSuccess.bagCode}</h3>
        <p className="text-ink">Current Living: {recordSuccess.resulting.toLocaleString()}</p>
        {recordSuccess.released && (
          <p className="text-xs text-ink-muted">
            Current Living: 0. Biological assignment released. The physical Grow Bag remains at its current
            Position — it has not been moved or freed for reuse.
          </p>
        )}
        <Button
          type="button" variant="primary" className="self-start"
          onClick={() => {
            setLossTargetBagId(null);
            setRecordSuccess(null);
            setRecordError(null);
          }}
        >
          Done
        </Button>
      </div>
    );
  }

  if (lossTargetBag) {
    return (
      <RecordGrowCubeLossForm
        // UX-OPS-001C/R1: keyed by target -- another Grow Bag can never
        // reuse this one's frozen attempt.
        key={lossTargetBag.batch_carrier_assignment_id}
        onCommandLockedChange={onCommandLockedChange}
        growBagCode={lossTargetBag.grow_bag.code}
        batchCarrierAssignmentId={lossTargetBag.batch_carrier_assignment_id}
        livingPlantCount={lossTargetBag.living_plant_count}
        growCubes={lossTargetBag.grow_cubes}
        isSubmitting={recordMutation.isPending}
        serverError={recordError}
        onCancel={() => {
          setLossTargetBagId(null);
          setRecordError(null);
        }}
        onSubmit={(payload) => {
          setRecordError(null);
          return recordMutation.mutateAsync(payload).then(
            (result) => {
              setRecordSuccess({
                bagCode: lossTargetBag.grow_bag.code, resulting: result.resulting_living_population,
                released: result.assignment_released,
              });
            },
            (error) => {
              const appError = asAppError(error);
              setRecordError(appError);
              throw appError;
            },
          );
        }}
      />
    );
  }

  if (detailQuery.isError) {
    return <ErrorState error={detailQuery.error} onRetry={() => detailQuery.refetch()} />;
  }
  if (bags.length === 0) return <p className="text-xs text-ink-muted">No Grow Bags currently hold this Batch here.</p>;

  return (
    <BoundedDataRegion label="Grow Bags">
      <ul className="flex flex-col divide-y divide-wl-border">
        {bags.map((bag) => {
          const actions = vinesGrowBagActions(farmId, batchId, bag);
          return (
            <li key={bag.grow_bag.id} className="flex flex-col gap-1 p-2 text-xs">
              <span className="font-medium text-ink">
                {bag.grow_bag.code} · {bag.grow_bag_position_code} · Living {bag.living_plant_count.toLocaleString()}
                {bag.capacity != null ? ` / ${bag.capacity.toLocaleString()}` : ""}
                {bag.free_capacity != null && bag.free_capacity > 0 ? ` · Free ${bag.free_capacity.toLocaleString()}` : ""}
              </span>
              <div className="flex flex-wrap gap-x-3 gap-y-1 text-ink-muted">
                {bag.grow_cubes.map((c) => (
                  <span key={c.grow_cube.id} className={c.status === "removed" ? "line-through opacity-60" : ""}>
                    {c.grow_cube.code}
                    {c.source_seed_tray ? ` ← ${c.source_seed_tray.code}` : ""}
                  </span>
                ))}
              </div>
              <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                {actions.map((action) =>
                  action.href ? (
                    <Link key={action.kind} href={action.href} className="inline-flex min-h-8 items-center font-medium text-wl-brand hover:underline">
                      {action.label}
                    </Link>
                  ) : (
                    <button
                      key={action.kind}
                      type="button"
                      onClick={() => setLossTargetBagId(bag.batch_carrier_assignment_id)}
                      className="min-h-8 rounded-md border border-border-subtle px-2 text-xs font-medium text-ink hover:bg-surface-subtle"
                    >
                      {action.label}
                    </button>
                  ),
                )}
              </div>
            </li>
          );
        })}
      </ul>
    </BoundedDataRegion>
  );
}
