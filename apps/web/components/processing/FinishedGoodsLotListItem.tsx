"use client";

import Link from "next/link";

import { findOpenRecallCase, RecallBadge } from "@/components/processing/RecallBadge";
import type { FinishedGoodsLotRead, RecallCaseSummaryRead } from "@/lib/api/client";
import { useFinishedGoodsPlacement } from "@/lib/query/hooks";

/** POSTHARVEST-OPS-001G: one Finished Goods Lot row -- net packed weight is
 * immutable (the Packing command's own output), while
 * available/placed/unplaced is fetched on demand from the Placement read
 * (no bulk placement endpoint exists, same rationale as
 * `GradedProduceLotListItem`'s own balance fetch), so dispatch-readiness is
 * never confused with the original packed quantity. */
export function FinishedGoodsLotListItem({
  lot,
  farmId,
  recallCases,
}: {
  lot: FinishedGoodsLotRead;
  farmId: string;
  recallCases: RecallCaseSummaryRead[] | undefined;
}) {
  const placementQuery = useFinishedGoodsPlacement(farmId, lot.id);
  const recallCase = findOpenRecallCase(recallCases, "finished_goods_lot_id", lot.id);

  return (
    <li className="flex flex-col gap-2 rounded-lg border border-border-subtle p-3 sm:flex-row sm:items-center sm:justify-between">
      <div className="flex flex-col gap-1">
        <Link
          href={`/farms/${farmId}/processing/finished-goods/${lot.id}`}
          className="text-sm font-semibold text-ink hover:underline"
        >
          {lot.code}
        </Link>
        <span className="text-xs text-ink-muted">
          {lot.crop.common_name}
          {lot.variety ? ` / ${lot.variety.name}` : ""} · {lot.source_graded_produce_lot_ids.length} source Graded Lot
          {lot.source_graded_produce_lot_ids.length === 1 ? "" : "s"}
        </span>
        <span className="text-xs text-ink-muted">
          Net packed {lot.net_packed_weight_kg} kg / {lot.package_count} packages
        </span>
        <span className="text-xs text-ink-muted">
          {placementQuery.data
            ? `Available ${placementQuery.data.available_weight_kg} kg / ${placementQuery.data.available_package_count} pkg — Placed ${placementQuery.data.total_placed_weight_kg} kg — Unplaced ${placementQuery.data.unplaced_weight_kg} kg`
            : placementQuery.isLoading
              ? "Loading placement…"
              : "Placement unavailable"}
        </span>
        <span className="text-xs text-ink-muted">{new Date(lot.effective_time).toLocaleString()}</span>
        <RecallBadge recallCase={recallCase} />
      </div>
    </li>
  );
}
