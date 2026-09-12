"use client";

import { useState } from "react";

import { ErrorState } from "@/components/ErrorState";
import { HarvestedProduceLotListItem } from "@/components/processing/HarvestedProduceLotListItem";
import { Button } from "@/components/ui/Button";
import type { HarvestedProduceLotRead, RecallCaseSummaryRead } from "@/lib/api/client";
import { useHarvestedProduceLotBalances } from "@/lib/query/hooks";

const BALANCE_EPSILON = 0.001;

/** PILOT-UX-002C: the Grading source-Lot work queue. Every visible Lot's
 * own balance is read up front (`useHarvestedProduceLotBalances`, no bulk
 * balance endpoint exists -- see that hook's own note) so "still gradeable"
 * is the authoritative live figure driving both each row's own label and
 * the fully-graded filter below, never a value calculated client-side from
 * incomplete history. Fully-graded Lots (balance confirmed at ~0) are
 * hidden by default so the floor's actual remaining work is what's in
 * front of the operator, with an explicit toggle to bring them back for
 * audit -- never dropped from the underlying list. */
export function HarvestedProduceLotPicker({
  lots,
  farmId,
  recallCases,
  selectedId,
  isLoading,
  isError,
  error,
  onRetry,
  onSelect,
}: {
  lots: HarvestedProduceLotRead[];
  farmId: string;
  recallCases: RecallCaseSummaryRead[] | undefined;
  selectedId: string | null;
  isLoading: boolean;
  isError: boolean;
  error?: unknown;
  onRetry: () => void;
  onSelect: (lot: HarvestedProduceLotRead) => void;
}) {
  const [showFullyGraded, setShowFullyGraded] = useState(false);
  const sorted = [...lots].sort((a, b) => b.effective_time.localeCompare(a.effective_time));
  const balances = useHarvestedProduceLotBalances(
    farmId,
    sorted.map((l) => l.id),
  );

  if (isLoading) {
    return <p className="text-sm text-ink-muted">Loading Harvested Produce Lots…</p>;
  }
  if (isError) {
    return <ErrorState error={error} onRetry={onRetry} />;
  }
  if (lots.length === 0) {
    return <p className="text-sm text-ink-muted">No Harvested Produce Lots recorded in this Farm yet.</p>;
  }

  const isFullyGraded = (lotId: string) => {
    const balance = balances[lotId];
    return balance != null && Number(balance.available_weight_kg) <= BALANCE_EPSILON;
  };
  const visible = showFullyGraded ? sorted : sorted.filter((lot) => !isFullyGraded(lot.id));
  const hiddenCount = sorted.length - visible.length;

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-sm font-semibold text-ink">Gradeable work queue</h3>
        {hiddenCount > 0 && (
          <Button type="button" variant="secondary" onClick={() => setShowFullyGraded((v) => !v)}>
            {showFullyGraded ? "Hide fully graded" : `Show ${hiddenCount} fully graded`}
          </Button>
        )}
      </div>
      {visible.length === 0 ? (
        <p className="text-sm text-ink-muted">No Lots currently have gradeable balance remaining.</p>
      ) : (
        <ul className="flex flex-col gap-3">
          {visible.map((lot) => {
            const isSelected = lot.id === selectedId;
            const balance = balances[lot.id];
            return (
              <HarvestedProduceLotListItem
                key={lot.id}
                lot={lot}
                balance={balance}
                isBalanceLoading={balance == null}
                recallCases={recallCases}
              >
                {() => (
                  <Button
                    type="button"
                    variant={isSelected ? "secondary" : "primary"}
                    className="self-start sm:self-center"
                    disabled={!isSelected && isFullyGraded(lot.id)}
                    onClick={() => onSelect(lot)}
                  >
                    {isSelected ? "Selected" : "Grade this Lot"}
                  </Button>
                )}
              </HarvestedProduceLotListItem>
            );
          })}
        </ul>
      )}
    </div>
  );
}
