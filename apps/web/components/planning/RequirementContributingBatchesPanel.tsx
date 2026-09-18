"use client";

import Link from "next/link";
import { useMemo } from "react";

import { EmptyState } from "@/components/EmptyState";
import { LoadingSkeleton } from "@/components/LoadingSkeleton";
import { RiskSignalBadge } from "@/components/planning/RiskSignalBadge";
import { formatQuantity } from "@/lib/format/planQuantity";
import {
  useBatchHarvestForecastStatuses,
  useSeedingProgramLineDetails,
  useSeedingProgramLinesForRequirement,
} from "@/lib/query/hooks";

/** PILOT-PLAN-001B section 4: "why does GrowCMP think this requirement is
 * short" -- the full lineage, never hidden: Requirement -> Seeding Program
 * Lines -> actual Sowings/Batches -> each Batch's forecast + actual
 * harvested. Composed entirely from existing PILOT-PLAN-001A endpoints
 * (Seeding Program Line detail's `linked_sowings`, Batch forecast status) --
 * no new backend read model. */
export function RequirementContributingBatchesPanel({ farmId, requirementId }: { farmId: string; requirementId: string }) {
  const linesQuery = useSeedingProgramLinesForRequirement(farmId, requirementId);
  const linkedLineIds = useMemo(
    () => (linesQuery.data ?? []).filter((l) => l.linked_sowing_count > 0).map((l) => l.id),
    [linesQuery.data],
  );
  const lineDetails = useSeedingProgramLineDetails(farmId, linkedLineIds);

  const batches = useMemo(() => {
    const seen = new Map<string, { batchId: string; batchCode: string }>();
    for (const lineId of linkedLineIds) {
      const detail = lineDetails.byLineId[lineId];
      for (const sowing of detail?.linked_sowings ?? []) {
        seen.set(sowing.batch_id, { batchId: sowing.batch_id, batchCode: sowing.batch_code });
      }
    }
    return [...seen.values()];
  }, [linkedLineIds, lineDetails.byLineId]);

  const batchIds = useMemo(() => batches.map((b) => b.batchId), [batches]);
  const statuses = useBatchHarvestForecastStatuses(farmId, batchIds);

  if (linesQuery.isLoading) return <LoadingSkeleton rows={2} label="Loading contributing batches" />;

  if (linkedLineIds.length === 0) {
    return <EmptyState title="No sowings recorded yet." description="No Batch contributes to this requirement's forecast until a plan line is sown." />;
  }
  if (lineDetails.isLoading || (batchIds.length > 0 && statuses.isLoading)) {
    return <LoadingSkeleton rows={2} label="Loading contributing batches" />;
  }

  return (
    <div className="overflow-x-auto rounded-lg border border-wl-border">
      <table className="w-full min-w-[720px] text-left text-sm">
        <thead className="bg-wl-surface-sunken text-xs font-medium uppercase tracking-wide text-wl-text-tertiary">
          <tr>
            <th scope="col" className="px-3 py-2">Batch</th>
            <th scope="col" className="px-3 py-2">Stage</th>
            <th scope="col" className="px-3 py-2">Forecast (expected)</th>
            <th scope="col" className="px-3 py-2">Harvested to date</th>
            <th scope="col" className="px-3 py-2">Risk</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-wl-border">
          {batches.map((batch) => {
            const status = statuses.byBatchId[batch.batchId];
            const forecast = status?.current_forecast;
            return (
              <tr key={batch.batchId} className="hover:bg-wl-surface-hover">
                <td className="whitespace-nowrap px-3 py-2">
                  <Link href={`/farms/${farmId}/crop-batches/${batch.batchId}`} className="font-medium text-wl-brand hover:underline">
                    {batch.batchCode}
                  </Link>
                </td>
                <td className="px-3 py-2 text-wl-text">{status?.current_stage.name ?? "—"}</td>
                <td className="whitespace-nowrap px-3 py-2 text-wl-text">
                  {forecast ? formatQuantity(forecast.expected_quantity, forecast.uom.code) : (
                    <span className="text-wl-text-secondary">No forecast</span>
                  )}
                </td>
                <td className="whitespace-nowrap px-3 py-2 text-wl-text">
                  {status ? formatQuantity(String(status.actual.total_harvested_weight_kg), "kg") : "—"}
                </td>
                <td className="px-3 py-2">
                  {status && <RiskSignalBadge farmId={farmId} batchId={batch.batchId} openCropIssueCount={status.open_crop_issue_count} />}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
