"use client";

import Link from "next/link";

import { useCropIssues } from "@/lib/query/hooks";

/** PILOT-PLAN-001B section 9: the only V1 risk signal is the open Crop
 * Issue count for a Batch (`open_crop_issue_count`, already computed by the
 * backend -- see docs/domain/HARVEST_FORECAST_CAPACITY_MODEL.md Part 8).
 * Never lowers a forecast, never marks a Batch failed, never infers
 * severity beyond the count itself -- a human decides whether a forecast
 * revision is warranted. Renders nothing for zero, so it never implies
 * "checked, no risk" where "no signal recorded" is the honest state.
 *
 * Opens the single open issue's own page when there is exactly one (the
 * count this badge shows already came from the backend, so this list fetch
 * only ever runs for a Batch known to have at least one) -- with several
 * open issues, there is no single correct target to jump to, so the badge
 * stays a plain (non-link) marker rather than guessing one. */
export function RiskSignalBadge({
  farmId,
  batchId,
  openCropIssueCount,
}: {
  farmId: string;
  batchId: string;
  openCropIssueCount: number;
}) {
  const issuesQuery = useCropIssues(farmId, batchId);
  if (openCropIssueCount <= 0) return null;

  const label = `${openCropIssueCount} open crop issue${openCropIssueCount === 1 ? "" : "s"}`;
  const className = "inline-flex items-center rounded-md bg-wl-flag-bg px-2 py-[3px] text-[11px] font-medium text-wl-flag-fg";
  const openIssues = (issuesQuery.data ?? []).filter((issue) => issue.status === "open");

  if (openIssues.length === 1) {
    return (
      <Link href={`/farms/${farmId}/crop-issues/${openIssues[0].id}`} className={`${className} hover:underline`}>
        {label}
      </Link>
    );
  }
  return <span className={className}>{label}</span>;
}
