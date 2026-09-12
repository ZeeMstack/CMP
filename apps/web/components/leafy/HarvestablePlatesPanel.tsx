"use client";

import { Button } from "@/components/ui/Button";
import type { HarvestablePlateRead } from "@/lib/api/client";

function locationLabel(location: HarvestablePlateRead["location"]): string | null {
  if (!location) return null;
  const parts = [location.greenhouse, location.zone, location.span, location.grow_table]
    .filter((slot): slot is NonNullable<typeof slot> => Boolean(slot))
    .map((slot) => slot.code);
  return parts.length > 0 ? parts.join(" / ") : null;
}

/** HARVEST-OPS-001 SLICE 2: the Plate picker for a new Leafy Harvest command.
 * A Quality-Held Plate is always VISIBLE here (never hidden), badged and
 * disabled for selection -- the write endpoint remains the sole authority
 * that actually blocks a new Harvest while the hold is open (mirrors
 * LEAFY-OPS-001's own "never hide, only flag" convention). Once at least
 * one Plate is selected (`lockedBatchId` set), every other-Batch row is
 * disabled with an explanatory reason rather than silently letting a
 * cross-Batch row be submitted and rejected server-side.
 *
 * PILOT-UX-003: compact row list (Waterline tokens) replacing the previous
 * heavier bordered-card-per-row treatment -- same Add/Remove semantics, no
 * domain change. */
export function HarvestablePlatesPanel({
  plates,
  selectedAssignmentIds,
  lockedBatchId,
  onAdd,
  onRemove,
  isLoading,
}: {
  plates: HarvestablePlateRead[];
  selectedAssignmentIds: string[];
  lockedBatchId: string | null;
  onAdd: (plate: HarvestablePlateRead) => void;
  onRemove: (assignmentId: string) => void;
  isLoading: boolean;
}) {
  if (isLoading) {
    return <p className="text-sm text-wl-text-secondary">Loading harvestable Plates…</p>;
  }
  if (plates.length === 0) {
    return <p className="text-sm text-wl-text-secondary">No harvestable Production Plates in this Farm.</p>;
  }

  return (
    <div className="overflow-hidden rounded-xl border border-wl-border bg-wl-surface-raised">
      <h3 className="border-b border-wl-border bg-wl-surface-sunken px-3 py-2 text-sm font-semibold text-wl-text">
        Add Plates
      </h3>
      <ul>
        {plates.map((plate) => {
          const isSelected = selectedAssignmentIds.includes(plate.current_batch_carrier_assignment_id);
          const isWrongBatch = lockedBatchId !== null && plate.batch_id !== lockedBatchId;
          const location = locationLabel(plate.location);
          return (
            <li
              key={plate.current_batch_carrier_assignment_id}
              className={`flex flex-col gap-2 border-b border-wl-border p-3 last:border-b-0 hover:bg-wl-surface-hover sm:flex-row sm:items-center sm:justify-between ${isSelected ? "bg-wl-brand-subtle" : ""}`}
            >
              <div className="flex flex-col gap-1">
                <span className="text-sm font-semibold text-wl-text">
                  {plate.production_plate_code} — {plate.batch_code}
                </span>
                <span className="text-xs text-wl-text-secondary">
                  {plate.crop_common_name}
                  {plate.variety_name ? ` / ${plate.variety_name}` : ""} · Living{" "}
                  {plate.current_living_heads.toLocaleString()}
                </span>
                {location ? (
                  <span className="text-xs text-wl-text-secondary">{location}</span>
                ) : (
                  <span className="text-xs text-wl-flag-fg">No current Leafy location on record</span>
                )}
                {plate.quality_hold_open && (
                  <span className="inline-flex w-fit items-center rounded-full bg-wl-flag-bg px-2 py-0.5 text-xs font-medium text-wl-flag-fg">
                    On quality hold — Harvest blocked
                  </span>
                )}
                {isWrongBatch && !isSelected && (
                  <span className="text-xs text-wl-text-secondary">
                    This Harvest is already recording against another Batch — only Plates from the same Batch can be
                    added.
                  </span>
                )}
              </div>
              {isSelected ? (
                <Button
                  type="button"
                  variant="secondary"
                  className="self-start sm:self-center"
                  onClick={() => onRemove(plate.current_batch_carrier_assignment_id)}
                >
                  Remove from Harvest
                </Button>
              ) : (
                <Button
                  type="button"
                  variant="primary"
                  className="self-start sm:self-center"
                  disabled={plate.quality_hold_open || isWrongBatch}
                  onClick={() => onAdd(plate)}
                >
                  Add to Harvest
                </Button>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
