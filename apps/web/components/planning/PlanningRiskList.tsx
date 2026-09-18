"use client";

import Link from "next/link";

import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { LoadingSkeleton } from "@/components/LoadingSkeleton";
import { useFarmHarvestForecastSummary } from "@/lib/query/hooks";

/** PILOT-PLAN-001B section 9/17: Overview's "Risks / Attention" section --
 * batches, forecasted in the current period, with an open Crop Issue. Never
 * infers severity or forecast impact -- purely a list of where a human
 * should look. Sourced from the same authoritative `open_crop_issue_count`
 * used everywhere else in this ticket (never a second, divergent risk
 * definition). */
export function PlanningRiskList({
  farmId,
  periodStart,
  periodEnd,
}: {
  farmId: string;
  periodStart: string;
  periodEnd: string;
}) {
  const summaryQuery = useFarmHarvestForecastSummary(farmId, periodStart, periodEnd);

  if (summaryQuery.isLoading) return <LoadingSkeleton rows={2} label="Loading risk signals" />;
  if (summaryQuery.error) return <ErrorState error={summaryQuery.error} onRetry={() => summaryQuery.refetch()} />;

  const atRisk = (summaryQuery.data ?? []).filter((b) => b.open_crop_issue_count > 0);
  if (atRisk.length === 0) {
    return <EmptyState title="No forecasted batches with open crop issues in this period." />;
  }

  return (
    <ul className="divide-y divide-wl-border rounded-lg border border-wl-border">
      {atRisk.map((batch) => (
        <li key={batch.batch_id} className="flex items-center justify-between gap-3 px-3.5 py-2 text-sm">
          <Link href={`/farms/${farmId}/crop-batches/${batch.batch_id}?tab=forecast`} className="font-medium text-wl-brand hover:underline">
            {batch.batch_code}
          </Link>
          <span className="text-wl-text-secondary">
            {batch.crop.common_name}
            {batch.variety ? ` · ${batch.variety.name}` : ""}
          </span>
          <span className="text-wl-flag-fg">
            {batch.open_crop_issue_count} open crop issue{batch.open_crop_issue_count === 1 ? "" : "s"}
          </span>
        </li>
      ))}
    </ul>
  );
}
