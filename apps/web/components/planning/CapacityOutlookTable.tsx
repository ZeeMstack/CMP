"use client";

import { Fragment, useMemo, useState } from "react";

import { Button } from "@/components/ui/Button";
import { CapacityAllocationForm } from "@/components/planning/CapacityAllocationForm";
import { CapacityAllocationList } from "@/components/planning/CapacityAllocationList";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { LoadingSkeleton } from "@/components/LoadingSkeleton";
import { StatusBadge } from "@/components/StatusBadge";
import { tableBodyDividerClass, tableHeadRowClass, tableRowHoverClass, tableTdClass, tableThClass, tableWrapperClass } from "@/components/ui/table";
import { AppError } from "@/lib/errors/adapter";
import { CAPACITY_STATUS_LABEL, deriveCapacityStatus, type CapacityStatus } from "@/lib/format/capacityStatus";
import { flattenLocationCapacityOptions } from "@/lib/format/locationTree";
import { useCapacityAllocations, useCreateCapacityAllocation, useLocationCapacitySummaries, useLocationsTree } from "@/lib/query/hooks";

function statusTone(status: CapacityStatus): "active" | "attention" | "critical" | "neutral" {
  if (status === "AVAILABLE") return "active";
  if (status === "FULL") return "attention";
  if (status === "OVER_COMMITTED") return "critical";
  return "neutral";
}

/** PILOT-PLAN-001B section 10-13: the Capacity Outlook worksheet.
 *
 * There is no farm-wide capacity-summary endpoint (the backend's read model
 * is deliberately Location+window scoped, see
 * docs/domain/HARVEST_FORECAST_CAPACITY_MODEL.md Part 4/6) and a farm's
 * Location tree can be very large, so this worksheet never blindly queries
 * every Location -- it tracks Locations that already have at least one
 * active Capacity Allocation on this farm, plus any the user explicitly
 * adds via the picker below (which then stay tracked, including across a
 * fresh allocation created against them). This is a truthful "what's
 * currently part of capacity planning" view, not "every Location that
 * could theoretically be allocated". */
export function CapacityOutlookTable({
  farmId,
  periodStart,
  periodEnd,
}: {
  farmId: string;
  periodStart: string;
  periodEnd: string;
}) {
  const allocationsQuery = useCapacityAllocations(farmId);
  const treeQuery = useLocationsTree(farmId);
  const [addedLocationIds, setAddedLocationIds] = useState<string[]>([]);
  const [pickerValue, setPickerValue] = useState("");
  const [expandedLocationId, setExpandedLocationId] = useState<string | null>(null);
  const [creatingForLocationId, setCreatingForLocationId] = useState<string | null>(null);

  const discoveredLocationIds = useMemo(
    () => [...new Set((allocationsQuery.data ?? []).filter((a) => a.status === "active").map((a) => a.location_id))],
    [allocationsQuery.data],
  );
  const trackedLocationIds = useMemo(
    () => [...new Set([...discoveredLocationIds, ...addedLocationIds])],
    [discoveredLocationIds, addedLocationIds],
  );

  const summaries = useLocationCapacitySummaries(farmId, trackedLocationIds, periodStart, periodEnd);
  const locationOptions = useMemo(() => flattenLocationCapacityOptions(treeQuery.data ?? []), [treeQuery.data]);
  const locationById = useMemo(() => new Map(locationOptions.map((o) => [o.id, o])), [locationOptions]);
  const pickableOptions = locationOptions.filter((o) => !trackedLocationIds.includes(o.id));

  const createMutation = useCreateCapacityAllocation(farmId);

  if (allocationsQuery.isLoading || treeQuery.isLoading) {
    return <LoadingSkeleton rows={4} label="Loading capacity outlook" />;
  }
  if (allocationsQuery.error) return <ErrorState error={allocationsQuery.error} onRetry={() => allocationsQuery.refetch()} />;
  if (treeQuery.error) return <ErrorState error={treeQuery.error} onRetry={() => treeQuery.refetch()} />;

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <select
          value={pickerValue}
          onChange={(e) => setPickerValue(e.target.value)}
          className="min-h-9 rounded-md border border-wl-border bg-wl-surface px-2 text-sm text-wl-text"
        >
          <option value="">Add a location to this outlook…</option>
          {pickableOptions.map((option) => (
            <option key={option.id} value={option.id}>
              {option.label}
            </option>
          ))}
        </select>
        <Button
          variant="secondary"
          disabled={!pickerValue}
          onClick={() => {
            if (!pickerValue) return;
            setAddedLocationIds((ids) => [...ids, pickerValue]);
            setPickerValue("");
          }}
        >
          Add
        </Button>
      </div>

      {trackedLocationIds.length === 0 ? (
        <EmptyState
          title="No locations tracked in this outlook yet."
          description="Add a location above to see its planned capacity for this period, or create an allocation against it."
        />
      ) : (
        <div className={tableWrapperClass}>
          <table className="w-full min-w-[900px] text-left text-sm">
            <thead className={tableHeadRowClass}>
              <tr>
                <th scope="col" className={tableThClass}>Location</th>
                <th scope="col" className={tableThClass}>Capacity unit</th>
                <th scope="col" className={tableThClass}>Authoritative capacity</th>
                <th scope="col" className={tableThClass}>Planned allocation</th>
                <th scope="col" className={tableThClass}>Planned available</th>
                <th scope="col" className={tableThClass}>Status</th>
                <th scope="col" className={tableThClass}><span className="sr-only">Action</span></th>
              </tr>
            </thead>
            <tbody className={tableBodyDividerClass}>
              {trackedLocationIds.map((locationId) => {
                const summary = summaries.byLocationId[locationId];
                const location = locationById.get(locationId);
                const status = deriveCapacityStatus(summary);
                const expanded = expandedLocationId === locationId;
                return (
                  <Fragment key={locationId}>
                    <tr className={tableRowHoverClass}>
                      <td className={tableTdClass}>
                        <button
                          type="button"
                          className="font-medium text-wl-brand hover:underline"
                          onClick={() => setExpandedLocationId(expanded ? null : locationId)}
                        >
                          {location ? `${location.name} (${location.code})` : locationId}
                        </button>
                      </td>
                      <td className={tableTdClass}>{summary?.capacity_unit ?? "position"}</td>
                      <td className={tableTdClass}>
                        {summaries.isLoading && !summary ? "…" : summary?.authoritative_capacity ?? "Capacity not configured"}
                      </td>
                      <td className={tableTdClass}>{summaries.isLoading && !summary ? "…" : summary?.planned_used_capacity ?? "—"}</td>
                      <td className={tableTdClass}>
                        {summaries.isLoading && !summary
                          ? "…"
                          : summary?.available_planned_capacity === null || summary?.available_planned_capacity === undefined
                            ? "—"
                            : `${summary.available_planned_capacity} planned available`}
                      </td>
                      <td className={tableTdClass}>
                        <StatusBadge label={CAPACITY_STATUS_LABEL[status]} tone={statusTone(status)} />
                      </td>
                      <td className={`${tableTdClass} whitespace-nowrap text-right`}>
                        <Button variant="secondary" onClick={() => setCreatingForLocationId(locationId)}>
                          New allocation
                        </Button>
                      </td>
                    </tr>
                    {expanded && (
                      <tr>
                        <td colSpan={7} className="bg-wl-surface-sunken px-3.5 py-3">
                          <CapacityAllocationList farmId={farmId} locationId={locationId} allocations={summary?.allocations ?? []} />
                        </td>
                      </tr>
                    )}
                    {creatingForLocationId === locationId && (
                      <tr>
                        <td colSpan={7} className="bg-wl-surface-sunken px-3.5 py-3">
                          <CapacityAllocationForm
                            farmId={farmId}
                            locationOptions={locationOptions}
                            defaultLocationId={locationId}
                            isSubmitting={createMutation.isPending}
                            serverError={createMutation.error instanceof AppError ? createMutation.error.message : null}
                            onCancel={() => setCreatingForLocationId(null)}
                            onSubmit={(payload) =>
                              createMutation.mutate(payload, { onSuccess: () => setCreatingForLocationId(null) })
                            }
                          />
                        </td>
                      </tr>
                    )}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
