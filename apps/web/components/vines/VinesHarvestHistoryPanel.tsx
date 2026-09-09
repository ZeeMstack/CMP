"use client";

import { useState } from "react";

import { CorrectVinesHarvestForm } from "@/components/vines/CorrectVinesHarvestForm";
import { Button } from "@/components/ui/Button";
import type { CorrectVinesHarvestSourceLineCreate, VinesHarvestEventRead, VinesHarvestSourceLineRead } from "@/lib/api/client";
import { AppError } from "@/lib/errors/adapter";
import { HARVEST_CORRECTION_REASONS } from "@/lib/validation/vinesHarvest";

function harvestLocationLabel(location: VinesHarvestSourceLineRead["harvest_location"]): string | null {
  if (!location) return null;
  const parts = [location.greenhouse, location.zone, location.span, location.gutter]
    .filter((slot): slot is NonNullable<typeof slot> => Boolean(slot))
    .map((slot) => slot.code);
  return parts.length > 0 ? parts.join(" / ") : null;
}

function harvestCorrectionReasonLabel(reasonCode: string): string {
  return HARVEST_CORRECTION_REASONS.find((r) => r.code === reasonCode)?.label ?? reasonCode;
}

/** VINES-OPS-003: compact recent Harvest history -- Harvest | Batch | Crop |
 * Raw Qty | Greenhouse | Source | Date, repeat harvests from the same Batch
 * appear as separate rows (never collapsed/deduplicated), human-readable
 * codes only, no raw UUIDs. Remains usable for a fully-corrected-to-zero
 * Lot (never disappears merely because its source Gutter's own weight was
 * voided). Mirrors `LeafyHarvestHistoryPanel.tsx`'s own established shape,
 * minus every heads/population field. */
export function VinesHarvestHistoryPanel({
  events,
  onCorrect,
  correctingLineId,
  isSubmitting,
  serverError,
}: {
  events: VinesHarvestEventRead[];
  onCorrect: (
    harvestEventId: string, harvestSourceLineId: string, payload: CorrectVinesHarvestSourceLineCreate,
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
              {event.produce_lot_code} — {event.batch_code} ({event.crop.common_name})
            </span>
            <span className="text-xs text-ink-muted">{new Date(event.effective_time).toLocaleString()}</span>
          </div>
          <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm sm:grid-cols-3">
            <div>
              <dt className="text-ink-muted">Original total</dt>
              <dd className="text-ink">{event.original_total_harvested_weight_kg} kg</dd>
            </div>
            <div>
              <dt className="text-ink-muted">Current corrected total</dt>
              <dd className="text-ink">{event.current_total_harvested_weight_kg} kg</dd>
            </div>
            <div>
              <dt className="text-ink-muted">Available (after Grading)</dt>
              <dd className="text-ink">{event.available_balance_weight_kg} kg</dd>
            </div>
          </dl>
          {event.note && <p className="text-xs text-ink-muted">{event.note}</p>}

          <ul className="divide-y divide-border-subtle text-sm">
            {event.source_lines.map((line) => (
              <li key={line.id} className="flex flex-col gap-2 py-2">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="text-ink">
                    {line.gutter.code} — original {line.original_harvested_weight_kg} kg, current{" "}
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
                {line.grow_bags.length > 0 && (
                  <span className="text-xs text-ink-muted">
                    Grow Bags present: {line.grow_bags.map((b) => b.code).join(", ")}
                  </span>
                )}
                {line.correction_history.length > 0 && (
                  <ul className="flex flex-col gap-1 pl-3 text-xs text-ink-muted">
                    {line.correction_history.map((c) => (
                      <li key={c.id}>
                        {c.is_void ? "Voided" : `Corrected to ${c.corrected_harvested_weight_kg} kg`}
                        {" — "}
                        {harvestCorrectionReasonLabel(c.reason_code)} ({new Date(c.recorded_time).toLocaleString()})
                        {c.note ? `: ${c.note}` : ""}
                      </li>
                    ))}
                  </ul>
                )}
                <div>
                  {openLineId === line.id ? (
                    <CorrectVinesHarvestForm
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
