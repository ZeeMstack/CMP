"use client";

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
 * cross-Batch row be submitted and rejected server-side. */
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
    return <p className="text-sm text-ink-muted">Loading harvestable Plates…</p>;
  }
  if (plates.length === 0) {
    return <p className="text-sm text-ink-muted">No harvestable Production Plates in this Farm.</p>;
  }

  return (
    <ul className="flex flex-col gap-3">
      {plates.map((plate) => {
        const isSelected = selectedAssignmentIds.includes(plate.current_batch_carrier_assignment_id);
        const isWrongBatch = lockedBatchId !== null && plate.batch_id !== lockedBatchId;
        const location = locationLabel(plate.location);
        return (
          <li
            key={plate.current_batch_carrier_assignment_id}
            className="flex flex-col gap-2 rounded-lg border border-border-subtle p-3 sm:flex-row sm:items-center sm:justify-between"
          >
            <div className="flex flex-col gap-1">
              <span className="text-sm font-semibold text-ink">
                {plate.production_plate_code} — {plate.batch_code}
              </span>
              <span className="text-xs text-ink-muted">
                {plate.crop_common_name}
                {plate.variety_name ? ` / ${plate.variety_name}` : ""} · Living{" "}
                {plate.current_living_heads.toLocaleString()}
              </span>
              {location ? (
                <span className="text-xs text-ink-muted">{location}</span>
              ) : (
                <span className="text-xs text-red-700">No current Leafy location on record</span>
              )}
              {plate.quality_hold_open && (
                <span className="inline-flex w-fit items-center rounded-full bg-red-100 px-2 py-0.5 text-xs font-medium text-red-800">
                  On quality hold — Harvest blocked
                </span>
              )}
              {isWrongBatch && !isSelected && (
                <span className="text-xs text-ink-muted">
                  This Harvest is already recording against {lockedBatchId ? "another Batch" : ""} — only Plates
                  from the same Batch can be added.
                </span>
              )}
            </div>
            {isSelected ? (
              <button
                type="button"
                onClick={() => onRemove(plate.current_batch_carrier_assignment_id)}
                className="min-h-11 self-start rounded-md border border-border-subtle px-4 text-sm font-medium text-ink hover:bg-surface-subtle sm:self-center"
              >
                Remove from Harvest
              </button>
            ) : (
              <button
                type="button"
                disabled={plate.quality_hold_open || isWrongBatch}
                onClick={() => onAdd(plate)}
                className="min-h-11 self-start rounded-md bg-brand-700 px-4 text-sm font-medium text-white hover:bg-brand-800 disabled:cursor-not-allowed disabled:opacity-50 sm:self-center"
              >
                Add to Harvest
              </button>
            )}
          </li>
        );
      })}
    </ul>
  );
}
