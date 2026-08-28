"use client";

import Link from "next/link";

import { findOpenRecallCase, RecallBadge } from "@/components/processing/RecallBadge";
import type { FinishedGoodsLotRead, RecallCaseSummaryRead } from "@/lib/api/client";
import { useFinishedGoodsPlacement } from "@/lib/query/hooks";

function SourceRow({
  lot,
  farmId,
  recallCases,
  isSelected,
  onAdd,
  onRemove,
}: {
  lot: FinishedGoodsLotRead;
  farmId: string;
  recallCases: RecallCaseSummaryRead[] | undefined;
  isSelected: boolean;
  onAdd: () => void;
  onRemove: () => void;
}) {
  const placementQuery = useFinishedGoodsPlacement(farmId, lot.id);
  const recallCase = findOpenRecallCase(recallCases, "finished_goods_lot_id", lot.id);
  const hasUnplaced = placementQuery.data ? Number(placementQuery.data.unplaced_weight_kg) > 0 : false;

  return (
    <li className="flex flex-col gap-2 rounded-lg border border-border-subtle p-3 sm:flex-row sm:items-center sm:justify-between">
      <div className="flex flex-col gap-1">
        <Link href={`/farms/${farmId}/processing/finished-goods/${lot.id}`} className="text-sm font-semibold text-ink hover:underline">
          {lot.code}
        </Link>
        <span className="text-xs text-ink-muted">
          {lot.crop.common_name}
          {lot.variety ? ` / ${lot.variety.name}` : ""}
        </span>
        <span className="text-xs text-ink-muted">
          {placementQuery.data
            ? `Unplaced ${placementQuery.data.unplaced_weight_kg} kg / ${placementQuery.data.unplaced_package_count} pkg`
            : placementQuery.isLoading
              ? "Loading placement…"
              : "Placement unavailable"}
        </span>
        <RecallBadge recallCase={recallCase} />
      </div>
      <div>
        {isSelected ? (
          <button
            type="button"
            onClick={onRemove}
            className="min-h-11 rounded-md border border-border-subtle px-4 text-sm font-medium text-ink hover:bg-surface-subtle"
          >
            Remove
          </button>
        ) : (
          <button
            type="button"
            disabled={!placementQuery.data || !hasUnplaced || Boolean(recallCase)}
            onClick={onAdd}
            className="min-h-11 rounded-md bg-brand-700 px-4 text-sm font-medium text-white hover:bg-brand-800 disabled:cursor-not-allowed disabled:opacity-50"
          >
            Add to Dispatch
          </button>
        )}
      </div>
    </li>
  );
}

/** PILOT-READY-001: the Finished Goods Lot picker for a new Dispatch
 * command. Mirrors `GradedProduceLotSourcePanel.tsx`'s own selection
 * pattern -- a zero-unplaced-balance or open-recall Lot is always visible
 * (never hidden), disabled with its reason shown, since the write endpoint
 * remains the sole authority that actually blocks Dispatch while recall
 * containment or an insufficient-unplaced-balance condition applies. */
export function DispatchSourcePanel({
  lots,
  farmId,
  recallCases,
  selectedIds,
  onAdd,
  onRemove,
  isLoading,
}: {
  lots: FinishedGoodsLotRead[];
  farmId: string;
  recallCases: RecallCaseSummaryRead[] | undefined;
  selectedIds: string[];
  onAdd: (lot: FinishedGoodsLotRead) => void;
  onRemove: (lotId: string) => void;
  isLoading: boolean;
}) {
  if (isLoading) {
    return <p className="text-sm text-ink-muted">Loading Finished Goods Lots…</p>;
  }
  if (lots.length === 0) {
    return <p className="text-sm text-ink-muted">No Finished Goods Lots available in this Farm.</p>;
  }

  const sorted = [...lots].sort((a, b) => b.effective_time.localeCompare(a.effective_time));

  return (
    <ul className="flex flex-col gap-3">
      {sorted.map((lot) => (
        <SourceRow
          key={lot.id}
          lot={lot}
          farmId={farmId}
          recallCases={recallCases}
          isSelected={selectedIds.includes(lot.id)}
          onAdd={() => onAdd(lot)}
          onRemove={() => onRemove(lot.id)}
        />
      ))}
    </ul>
  );
}
