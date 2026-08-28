"use client";

import { GradedProduceLotListItem } from "@/components/processing/GradedProduceLotListItem";
import { Button } from "@/components/ui/Button";
import type { GradedProduceLotRead, RecallCaseSummaryRead } from "@/lib/api/client";

/** POSTHARVEST-OPS-001G: the Graded Produce Lot picker for a new Packing
 * command. Mirrors `HarvestablePlatesPanel.tsx`'s own "lock to one Crop once
 * a first row is added" convention exactly: a Packing command's inputs must
 * share one Crop/Variety with the chosen Pack Specification Version (see
 * `PackingCropVarietyMismatchError`), so once at least one Lot is selected,
 * every other-Crop row is disabled with an explanatory reason rather than
 * silently letting a cross-Crop row be submitted and rejected server-side.
 * A zero-balance or open-recall Lot is always visible (never hidden), badged
 * and disabled -- the write endpoint remains the sole authority that
 * actually blocks Packing while a hold/recall is open. */
export function GradedProduceLotSourcePanel({
  lots,
  farmId,
  gradeLabels,
  recallCases,
  selectedIds,
  lockedCropId,
  onAdd,
  onRemove,
  isLoading,
}: {
  lots: GradedProduceLotRead[];
  farmId: string;
  gradeLabels: Record<string, string>;
  recallCases: RecallCaseSummaryRead[] | undefined;
  selectedIds: string[];
  lockedCropId: string | null;
  onAdd: (lot: GradedProduceLotRead) => void;
  onRemove: (lotId: string) => void;
  isLoading: boolean;
}) {
  if (isLoading) {
    return <p className="text-sm text-ink-muted">Loading Graded Produce Lots…</p>;
  }
  if (lots.length === 0) {
    return <p className="text-sm text-ink-muted">No Graded Produce Lots available in this Farm.</p>;
  }

  const sorted = [...lots].sort((a, b) => b.effective_time.localeCompare(a.effective_time));

  return (
    <ul className="flex flex-col gap-3">
      {sorted.map((lot) => {
        const isSelected = selectedIds.includes(lot.id);
        const isWrongCrop = lockedCropId !== null && lot.crop.id !== lockedCropId;
        return (
          <GradedProduceLotListItem
            key={lot.id}
            lot={lot}
            farmId={farmId}
            gradeLabel={gradeLabels[lot.grade_definition_version_id] ?? ""}
            recallCases={recallCases}
          >
            {(balance) => {
              const hasBalance = balance ? Number(balance.available_weight_kg) > 0 : false;
              return (
                <div className="flex flex-col items-start gap-1 sm:items-end">
                  {isWrongCrop && !isSelected && (
                    <span className="max-w-48 text-right text-xs text-ink-muted">
                      Only Lots matching the Crop already in this Packing can be added.
                    </span>
                  )}
                  {isSelected ? (
                    <Button type="button" variant="secondary" onClick={() => onRemove(lot.id)}>
                      Remove
                    </Button>
                  ) : (
                    <Button
                      type="button"
                      variant="primary"
                      disabled={isWrongCrop || !balance || !hasBalance}
                      onClick={() => onAdd(lot)}
                    >
                      Add to Packing
                    </Button>
                  )}
                </div>
              );
            }}
          </GradedProduceLotListItem>
        );
      })}
    </ul>
  );
}
