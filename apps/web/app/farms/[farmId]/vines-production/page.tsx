"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";

import { Breadcrumbs } from "@/components/Breadcrumbs";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { LoadingSkeleton } from "@/components/LoadingSkeleton";
import { PageHeader } from "@/components/PageHeader";
import { RecordGrowCubeLossForm } from "@/components/vines/RecordGrowCubeLossForm";
import { VinesLossHistoryPanel } from "@/components/vines/VinesLossHistoryPanel";
import { Button } from "@/components/ui/Button";
import { Tabs } from "@/components/ui/Tabs";
import type { VinesProductionPlacementGrowBagRead } from "@/lib/api/client";
import { AppError } from "@/lib/errors/adapter";
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

function asAppError(error: unknown): AppError {
  return error instanceof AppError ? error : new AppError("server_error", "Something went wrong. Please try again.");
}

/** VINES-OPS-001B/VINES-OPS-002: the real Vines Production operational
 * workspace -- "Population" (compact aggregated Batch/Gutter rows, drill
 * down to Grow Bag/Grow Cube, Record Plant Loss inline) and "Loss History"
 * (correction). Mirrors `leafy-production/page.tsx`'s own established
 * two-section shape for the sibling authority. The 001B Transfer workflow
 * remains its own separate nav entry (`vines-production/transfer`),
 * untouched. */
export default function VinesProductionPage() {
  const { farmId } = useParams<{ farmId: string }>();
  const [tab, setTab] = useState<"population" | "history">("population");
  const [expanded, setExpanded] = useState<{ batchId: string; gutterId: string } | null>(null);

  const placementsQuery = useVinesProductionPlacements(farmId);
  const historyQuery = useVinesProductionDispositionHistory(farmId);
  const correctMutation = useCorrectVinesGrowCubeDisposition(farmId);
  const [correctingEventId, setCorrectingEventId] = useState<string | null>(null);
  const [correctError, setCorrectError] = useState<AppError | null>(null);

  return (
    <div>
      <PageHeader
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

      <div className="mb-6">
        <Tabs
          tabs={TABS.map(({ id, label }) => ({ id, label }))}
          activeId={tab}
          onChange={(id) => setTab(id as "population" | "history")}
          aria-label="Vines Production sections"
        />
      </div>

      {tab === "population" && (
        <>
          {placementsQuery.isLoading && <LoadingSkeleton rows={4} label="Loading Vines Production placements" />}
          {placementsQuery.isError && (
            <ErrorState error={placementsQuery.error} onRetry={() => placementsQuery.refetch()} />
          )}
          {placementsQuery.isSuccess && (placementsQuery.data ?? []).length === 0 && (
            <EmptyState
              title="Nothing is currently in Vines Production."
              description="Plants appear here once a Transfer to Production has placed living plants in a Grow Gutter."
            />
          )}
          {placementsQuery.isSuccess && (placementsQuery.data ?? []).length > 0 && (
            <div className="overflow-x-auto rounded-xl border border-border-subtle bg-surface">
              <table className="w-full min-w-[820px] text-left text-sm">
                <thead>
                  <tr className="border-b border-border-subtle text-ink-muted">
                    <th className="p-3 font-medium">Batch</th>
                    <th className="p-3 font-medium">Crop</th>
                    <th className="p-3 font-medium">Variety</th>
                    <th className="p-3 font-medium">Greenhouse</th>
                    <th className="p-3 font-medium">Gutter</th>
                    <th className="p-3 font-medium">Living Plants</th>
                    <th className="p-3 font-medium">Lost</th>
                    <th className="p-3 font-medium">Days in Production</th>
                    <th className="p-3 font-medium" />
                  </tr>
                </thead>
                <tbody>
                  {(placementsQuery.data ?? []).map((row) => {
                    const key = `${row.batch_id}:${row.gutter_id}`;
                    const isExpanded = expanded?.batchId === row.batch_id && expanded?.gutterId === row.gutter_id;
                    return (
                      <>
                        <tr key={key} className="border-b border-border-subtle last:border-0">
                          <td className="p-3 text-ink">{row.batch_code}</td>
                          <td className="p-3 text-ink">{row.crop_common_name}</td>
                          <td className="p-3 text-ink">{row.variety_name ?? "—"}</td>
                          <td className="p-3 text-ink">{row.greenhouse_code}</td>
                          <td className="p-3 text-ink">{row.gutter_code}</td>
                          <td className="p-3 text-ink">{row.living_plant_count.toLocaleString()}</td>
                          <td className="p-3 text-ink">
                            {row.lost_plant_count > 0 ? (
                              <span className="text-red-700">{row.lost_plant_count.toLocaleString()}</span>
                            ) : (
                              row.lost_plant_count.toLocaleString()
                            )}
                          </td>
                          <td className="p-3 text-ink">{row.days_in_production}</td>
                          <td className="p-3">
                            <div className="flex flex-wrap gap-2">
                              <button
                                type="button"
                                onClick={() => setExpanded(isExpanded ? null : { batchId: row.batch_id, gutterId: row.gutter_id })}
                                className="min-h-9 rounded-md border border-border-subtle px-3 text-xs font-medium text-ink hover:bg-surface-subtle"
                              >
                                {isExpanded ? "Hide Grow Bags" : "Grow Bags"}
                              </button>
                              <Link
                                href={`/farms/${farmId}/observations?batchId=${row.batch_id}`}
                                className="flex min-h-9 items-center rounded-md border border-border-subtle px-3 text-xs font-medium text-ink hover:bg-surface-subtle"
                              >
                                Record observation
                              </Link>
                            </div>
                          </td>
                        </tr>
                        {isExpanded && (
                          <tr key={`${key}-detail`} className="border-b border-border-subtle bg-surface-subtle last:border-0">
                            <td colSpan={9} className="p-3">
                              <GrowBagDrillDown farmId={farmId} batchId={row.batch_id} gutterId={row.gutter_id} />
                            </td>
                          </tr>
                        )}
                      </>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}

      {tab === "history" && (
        <VinesLossHistoryPanel
          lineages={historyQuery.data ?? []}
          // Backend enforces BIOLOGICAL_DISPOSITION_CORRECT authoritatively --
          // mirrors PlantLossHistoryPanel's own established rationale.
          canCorrect={true}
          correctingEventId={correctingEventId}
          isSubmitting={correctMutation.isPending}
          serverError={correctError}
          onCorrect={async (eventId: string) => {
            setCorrectingEventId(eventId);
            setCorrectError(null);
            try {
              await correctMutation.mutateAsync({ eventId, payload: { client_command_id: crypto.randomUUID() } });
            } catch (error) {
              setCorrectError(asAppError(error));
              throw error;
            } finally {
              setCorrectingEventId(null);
            }
          }}
        />
      )}
    </div>
  );
}

function GrowBagDrillDown({ farmId, batchId, gutterId }: { farmId: string; batchId: string; gutterId: string }) {
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
          recordMutation.mutate(payload, {
            onSuccess: (result) => {
              setRecordSuccess({
                bagCode: lossTargetBag.grow_bag.code, resulting: result.resulting_living_population,
                released: result.assignment_released,
              });
            },
            onError: (error) => setRecordError(asAppError(error)),
          });
        }}
      />
    );
  }

  return (
    <ul className="flex flex-col gap-2">
      {bags.map((bag) => (
        <li key={bag.grow_bag.id} className="rounded-md border border-border-subtle bg-surface p-2 text-xs">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="font-medium text-ink">
              {bag.grow_bag.code} · {bag.grow_bag_position_code} · Living {bag.living_plant_count.toLocaleString()}
              {bag.capacity != null ? ` / ${bag.capacity.toLocaleString()}` : ""}
              {bag.free_capacity != null && bag.free_capacity > 0 ? ` · Free ${bag.free_capacity.toLocaleString()}` : ""}
            </span>
            {bag.living_plant_count > 0 && (
              <button
                type="button"
                onClick={() => setLossTargetBagId(bag.batch_carrier_assignment_id)}
                className="min-h-8 rounded-md border border-border-subtle px-2 text-xs font-medium text-ink hover:bg-surface-subtle"
              >
                Record plant loss
              </button>
            )}
          </div>
          <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-ink-muted">
            {bag.grow_cubes.map((c) => (
              <span key={c.grow_cube.id} className={c.status === "removed" ? "line-through opacity-60" : ""}>
                {c.grow_cube.code}
                {c.source_seed_tray ? ` ← ${c.source_seed_tray.code}` : ""}
              </span>
            ))}
          </div>
        </li>
      ))}
    </ul>
  );
}
