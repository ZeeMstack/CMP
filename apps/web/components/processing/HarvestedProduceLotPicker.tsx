"use client";

import { Button } from "@/components/ui/Button";
import type { HarvestedProduceLotRead } from "@/lib/api/client";

/** POSTHARVEST-OPS-001G: the source-Lot picker for a new Grading command.
 * No "gradeable" filter exists on the list endpoint (unlike Harvest's own
 * `harvestable-plates` read), so every Harvested Produce Lot in the Farm is
 * shown, newest first; the operator's own knowledge of what still needs
 * grading is what narrows this in practice on the packhouse floor. Once a
 * row is selected, its live balance is fetched separately (see the parent
 * page) to show "available to grade" before the Grading form seeds its
 * defaults from it. */
export function HarvestedProduceLotPicker({
  lots,
  selectedId,
  onSelect,
  isLoading,
}: {
  lots: HarvestedProduceLotRead[];
  selectedId: string | null;
  onSelect: (lot: HarvestedProduceLotRead) => void;
  isLoading: boolean;
}) {
  if (isLoading) {
    return <p className="text-sm text-ink-muted">Loading Harvested Produce Lots…</p>;
  }
  if (lots.length === 0) {
    return <p className="text-sm text-ink-muted">No Harvested Produce Lots recorded in this Farm yet.</p>;
  }

  const sorted = [...lots].sort((a, b) => b.effective_time.localeCompare(a.effective_time));

  return (
    <ul className="flex flex-col gap-3">
      {sorted.map((lot) => {
        const isSelected = lot.id === selectedId;
        return (
          <li
            key={lot.id}
            className={`flex flex-col gap-2 rounded-xl border p-3 sm:flex-row sm:items-center sm:justify-between ${
              isSelected ? "border-brand-700 bg-brand-100/40" : "border-border-subtle bg-surface"
            }`}
          >
            <div className="flex flex-col gap-1">
              <span className="font-serif text-sm font-semibold text-ink">{lot.code}</span>
              <span className="text-xs text-ink-muted">
                {lot.crop.common_name}
                {lot.variety ? ` / ${lot.variety.name}` : ""} · Original {lot.total_harvested_weight_kg} kg
                {lot.total_whole_unit_count != null ? ` / ${lot.total_whole_unit_count} units` : ""}
              </span>
              <span className="text-xs text-ink-muted">{new Date(lot.effective_time).toLocaleString()}</span>
            </div>
            <Button
              type="button"
              variant={isSelected ? "secondary" : "primary"}
              className="self-start sm:self-center"
              onClick={() => onSelect(lot)}
            >
              {isSelected ? "Selected" : "Grade this Lot"}
            </Button>
          </li>
        );
      })}
    </ul>
  );
}
