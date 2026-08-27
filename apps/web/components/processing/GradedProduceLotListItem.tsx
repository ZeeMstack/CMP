"use client";

import Link from "next/link";
import type { ReactNode } from "react";

import { findOpenRecallCase, RecallBadge } from "@/components/processing/RecallBadge";
import type { GradedProduceLotBalanceRead, GradedProduceLotRead, RecallCaseSummaryRead } from "@/lib/api/client";
import { useGradedProduceLotBalance } from "@/lib/query/hooks";

/** POSTHARVEST-OPS-001G: one Graded Produce Lot row, reused by the Graded
 * Produce Lots list and the Packing input picker. Fetches this Lot's own
 * balance on demand (no bulk balance endpoint exists -- see
 * `useGradedProduceLotBalance`'s own note) so "current available
 * weight/count" is always live, never the immutable `original_received_*`
 * fields mistaken for it. `children` is a render prop so callers can key an
 * action (a detail link, an "Add to Packing" button) off the fetched
 * balance without duplicating the fetch. */
export function GradedProduceLotListItem({
  lot,
  farmId,
  gradeLabel,
  recallCases,
  children,
}: {
  lot: GradedProduceLotRead;
  farmId: string;
  gradeLabel: string;
  recallCases: RecallCaseSummaryRead[] | undefined;
  children?: (balance: GradedProduceLotBalanceRead | undefined, isLoading: boolean) => ReactNode;
}) {
  const balanceQuery = useGradedProduceLotBalance(farmId, lot.id);
  const recallCase = findOpenRecallCase(recallCases, "graded_produce_lot_id", lot.id);
  const isCountMode = lot.original_received_whole_unit_count != null;

  return (
    <li className="flex flex-col gap-2 rounded-lg border border-border-subtle p-3 sm:flex-row sm:items-center sm:justify-between">
      <div className="flex flex-col gap-1">
        <Link
          href={`/farms/${farmId}/processing/graded-lots/${lot.id}`}
          className="text-sm font-semibold text-ink hover:underline"
        >
          {lot.code}
        </Link>
        <span className="text-xs text-ink-muted">
          {lot.crop.common_name}
          {lot.variety ? ` / ${lot.variety.name}` : ""} ·{" "}
          {gradeLabel || `Grade version ${lot.grade_definition_version_id.slice(0, 8)}`}
        </span>
        <span className="text-xs text-ink-muted">
          Original {lot.original_received_weight_kg} kg
          {isCountMode ? ` / ${lot.original_received_whole_unit_count} units` : ""}
        </span>
        <span className="text-xs text-ink-muted">
          Available{" "}
          {balanceQuery.data
            ? `${balanceQuery.data.available_weight_kg} kg${
                isCountMode ? ` / ${balanceQuery.data.available_whole_unit_count} units` : ""
              }`
            : balanceQuery.isLoading
              ? "Loading…"
              : "Unavailable"}
        </span>
        <span className="text-xs text-ink-muted">{new Date(lot.effective_time).toLocaleString()}</span>
        <RecallBadge recallCase={recallCase} />
      </div>
      {children?.(balanceQuery.data, balanceQuery.isLoading)}
    </li>
  );
}
