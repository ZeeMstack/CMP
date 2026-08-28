"use client";

import { useState } from "react";

import { CorrectHarvestForm } from "@/components/leafy/CorrectHarvestForm";
import { Button } from "@/components/ui/Button";
import type { CorrectLeafyHarvestSourceLineCreate, LeafyHarvestEventRead, LeafyHarvestSourceLineRead } from "@/lib/api/client";
import { AppError } from "@/lib/errors/adapter";
import { HARVEST_CORRECTION_REASONS } from "@/lib/validation/leafyHarvest";

function harvestLocationLabel(location: LeafyHarvestSourceLineRead["harvest_location"]): string | null {
  if (!location) return null;
  const parts = [location.greenhouse, location.zone, location.span, location.grow_table]
    .filter((slot): slot is NonNullable<typeof slot> => Boolean(slot))
    .map((slot) => slot.code);
  return parts.length > 0 ? parts.join(" / ") : null;
}

// Reuses `HARVEST_CORRECTION_REASONS` -- the exact same reason options
// `CorrectHarvestForm` populates its own <select> from -- so History and
// the Correction form can never drift apart into two different label
// mappings. API reason codes stored/sent to the backend are unchanged;
// this only affects what the operator reads here. An unrecognized code
// (e.g. legacy data) falls back to the raw code rather than hiding it.
function harvestCorrectionReasonLabel(reasonCode: string): string {
  return HARVEST_CORRECTION_REASONS.find((r) => r.code === reasonCode)?.label ?? reasonCode;
}

/** HARVEST-OPS-001 SLICE 2: Harvest History -- both the immutable ORIGINAL
 * Lot totals and the structurally-resolved CURRENT corrected totals are
 * shown, never one collapsed into the other (ticket section N). Remains
 * usable for a fully zero-harvested Lot (it never disappears merely
 * because its source Plate left the Harvestable Plates list). */
export function LeafyHarvestHistoryPanel({
  events,
  onCorrect,
  correctingLineId,
  isSubmitting,
  serverError,
}: {
  events: LeafyHarvestEventRead[];
  onCorrect: (
    harvestEventId: string, harvestSourceLineId: string, payload: CorrectLeafyHarvestSourceLineCreate,
  ) => Promise<void>;
  correctingLineId: string | null;
  isSubmitting: boolean;
  serverError?: AppError | null;
}) {
  const [openLineId, setOpenLineId] = useState<string | null>(null);

  if (events.length === 0) {
    return <p className="text-sm text-ink-muted">No Harvests recorded yet.</p>;
  }

  return (
    <ul className="flex flex-col gap-4">
      {events.map((event) => (
        <li key={event.id} className="flex flex-col gap-3 rounded-xl border border-border-subtle bg-surface p-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="font-serif text-sm font-semibold text-ink">
              {event.produce_lot_code} — {event.batch_code}
            </span>
            <span className="text-xs text-ink-muted">{new Date(event.effective_time).toLocaleString()}</span>
          </div>
          <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm sm:grid-cols-4">
            <div>
              <dt className="text-ink-muted">Original total</dt>
              <dd className="text-ink">
                {event.original_total_whole_unit_count ?? "—"} heads / {event.original_total_harvested_weight_kg} kg
              </dd>
            </div>
            <div>
              <dt className="text-ink-muted">Current corrected total</dt>
              <dd className="text-ink">
                {event.current_total_whole_unit_count} heads / {event.current_total_harvested_weight_kg} kg
              </dd>
            </div>
            <div>
              <dt className="text-ink-muted">Available (after Packing)</dt>
              <dd className="text-ink">
                {event.available_balance_whole_unit_count ?? "—"} heads / {event.available_balance_weight_kg} kg
              </dd>
            </div>
          </dl>
          {event.note && <p className="text-xs text-ink-muted">{event.note}</p>}

          <ul className="divide-y divide-border-subtle text-sm">
            {event.source_lines.map((line) => (
              <li key={line.id} className="flex flex-col gap-2 py-2">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="text-ink">
                    {line.carrier.code} — original {line.original_whole_unit_count ?? "—"} heads /{" "}
                    {line.original_harvested_weight_kg} kg, current {line.current_whole_unit_count} heads /{" "}
                    {line.current_harvested_weight_kg} kg
                  </span>
                  <span
                    className={`inline-flex w-fit items-center rounded-full px-2 py-0.5 text-xs font-medium ${
                      line.state === "VOID" ? "bg-red-100 text-red-800" : "bg-green-100 text-green-800"
                    }`}
                  >
                    {line.state}
                  </span>
                </div>
                {harvestLocationLabel(line.harvest_location) ? (
                  <span className="text-xs text-ink-muted">
                    Harvested at: {harvestLocationLabel(line.harvest_location)}
                  </span>
                ) : (
                  <span className="text-xs text-ink-muted">Harvest-time location unavailable</span>
                )}
                {line.correction_history.length > 0 && (
                  <ul className="flex flex-col gap-1 pl-3 text-xs text-ink-muted">
                    {line.correction_history.map((c) => (
                      <li key={c.id}>
                        {c.is_void ? "Voided" : `Corrected to ${c.corrected_whole_unit_count} heads / ${c.corrected_harvested_weight_kg} kg`}
                        {" — "}
                        {harvestCorrectionReasonLabel(c.reason_code)} ({new Date(c.recorded_time).toLocaleString()})
                        {c.note ? `: ${c.note}` : ""}
                      </li>
                    ))}
                  </ul>
                )}
                <div>
                  {openLineId === line.id ? (
                    <CorrectHarvestForm
                      sourceLine={line}
                      onSubmit={(payload) => onCorrect(event.id, line.id, payload)}
                      onCancel={() => setOpenLineId(null)}
                      isSubmitting={isSubmitting && correctingLineId === line.id}
                      serverError={correctingLineId === line.id ? serverError : null}
                    />
                  ) : (
                    <Button type="button" variant="secondary" onClick={() => setOpenLineId(line.id)}>
                      Correct Harvest
                    </Button>
                  )}
                </div>
              </li>
            ))}
          </ul>
        </li>
      ))}
    </ul>
  );
}
