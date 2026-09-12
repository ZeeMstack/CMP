"use client";

import type { ReactNode } from "react";

import { findOpenRecallCase, RecallBadge } from "@/components/processing/RecallBadge";
import { StatusBadge } from "@/components/StatusBadge";
import type { HarvestedProduceLotRead, ProduceLotBalanceRead, RecallCaseSummaryRead } from "@/lib/api/client";

const BALANCE_EPSILON = 0.001;

/** PILOT-UX-002C: one Harvested Produce Lot row in the Grading work queue.
 * Purely presentational -- the parent `HarvestedProduceLotPicker` fetches
 * every visible row's balance up front (via `useHarvestedProduceLotBalances`)
 * so the "fully graded" filter/count and each row's own label are always
 * computed from the same read, never out of sync with each other. Mirrors
 * `GradedProduceLotListItem`'s "current available, not original total" shape
 * exactly, plus a `children` render prop for the row's own action. */
export function HarvestedProduceLotListItem({
  lot,
  balance,
  isBalanceLoading,
  recallCases,
  children,
}: {
  lot: HarvestedProduceLotRead;
  balance: ProduceLotBalanceRead | undefined;
  isBalanceLoading: boolean;
  recallCases: RecallCaseSummaryRead[] | undefined;
  children?: (balance: ProduceLotBalanceRead | undefined) => ReactNode;
}) {
  const recallCase = findOpenRecallCase(recallCases, "harvested_produce_lot_id", lot.id);
  const hasCounts = lot.total_whole_unit_count != null;
  const isFullyGraded = balance != null && Number(balance.available_weight_kg) <= BALANCE_EPSILON;

  return (
    <li className="flex flex-col gap-2 rounded-xl border border-border-subtle bg-surface p-3 sm:flex-row sm:items-center sm:justify-between">
      <div className="flex flex-col gap-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-serif text-sm font-semibold text-ink">{lot.code}</span>
          {balance && (
            <StatusBadge
              label={isFullyGraded ? "Fully graded" : "Gradeable"}
              tone={isFullyGraded ? "neutral" : "active"}
            />
          )}
        </div>
        <span className="text-xs text-ink-muted">
          {lot.crop.common_name}
          {lot.variety ? ` / ${lot.variety.name}` : ""} · Harvested {lot.total_harvested_weight_kg} kg
          {hasCounts ? ` / ${lot.total_whole_unit_count} units` : ""}
        </span>
        <span className="text-xs font-semibold text-ink">
          {balance
            ? `Gradeable now ${balance.available_weight_kg} kg${
                hasCounts ? ` / ${balance.available_whole_unit_count} units` : ""
              }`
            : isBalanceLoading
              ? "Checking gradeable balance…"
              : "Gradeable balance unavailable"}
        </span>
        <span className="text-xs text-ink-muted">{new Date(lot.effective_time).toLocaleString()}</span>
        <RecallBadge recallCase={recallCase} />
      </div>
      {children?.(balance)}
    </li>
  );
}
