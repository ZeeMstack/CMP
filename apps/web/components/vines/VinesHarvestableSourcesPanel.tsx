"use client";

import { Button } from "@/components/ui/Button";
import type { VinesHarvestableSourceRead } from "@/lib/api/client";

/** VINES-OPS-003: the Gutter picker for a new Vines Harvest command --
 * mirrors `HarvestablePlatesPanel.tsx`'s own established shape exactly. A
 * quality-held Batch's Gutters are always VISIBLE here (never hidden),
 * badged and disabled for selection -- the write endpoint remains the sole
 * authority that actually blocks a new Harvest while the hold is open.
 * Once at least one Gutter is selected (`lockedBatchId` set), every
 * other-Batch row is disabled with an explanatory reason rather than
 * silently letting a cross-Batch row be submitted and rejected server-side.
 * Repeat harvest is normal here -- a Gutter with a recent `lastHarvest`
 * date remains fully selectable, never treated as "already harvested". */
export function VinesHarvestableSourcesPanel({
  sources,
  selectedGutterIds,
  lockedBatchId,
  onAdd,
  onRemove,
  isLoading,
}: {
  sources: VinesHarvestableSourceRead[];
  selectedGutterIds: string[];
  lockedBatchId: string | null;
  onAdd: (source: VinesHarvestableSourceRead) => void;
  onRemove: (gutterId: string) => void;
  isLoading: boolean;
}) {
  if (isLoading) {
    return <p className="text-sm text-ink-muted">Loading harvestable Gutters…</p>;
  }
  if (sources.length === 0) {
    return <p className="text-sm text-ink-muted">No harvestable Vines Production Gutters in this Farm.</p>;
  }

  return (
    <div className="overflow-x-auto rounded-xl border border-border-subtle bg-surface">
      <table className="w-full min-w-[760px] text-left text-sm">
        <thead>
          <tr className="border-b border-border-subtle text-ink-muted">
            <th className="p-3 font-medium">Batch</th>
            <th className="p-3 font-medium">Crop</th>
            <th className="p-3 font-medium">Variety</th>
            <th className="p-3 font-medium">Greenhouse</th>
            <th className="p-3 font-medium">Gutter</th>
            <th className="p-3 font-medium">Living Plants</th>
            <th className="p-3 font-medium">Last Harvest</th>
            <th className="p-3 font-medium" />
          </tr>
        </thead>
        <tbody>
          {sources.map((s) => {
            const isSelected = selectedGutterIds.includes(s.gutter_id);
            const isWrongBatch = lockedBatchId !== null && s.batch_id !== lockedBatchId;
            return (
              <tr key={s.gutter_id} className="border-b border-border-subtle last:border-0">
                <td className="p-3 text-ink">{s.batch_code}</td>
                <td className="p-3 text-ink">{s.crop_common_name}</td>
                <td className="p-3 text-ink">{s.variety_name ?? "—"}</td>
                <td className="p-3 text-ink">{s.greenhouse_code}</td>
                <td className="p-3 text-ink">
                  {s.gutter_code}
                  {s.quality_hold_open && (
                    <span className="ml-2 inline-flex w-fit items-center rounded-full bg-red-100 px-2 py-0.5 text-xs font-medium text-red-800">
                      Quality hold
                    </span>
                  )}
                </td>
                <td className="p-3 text-ink">{s.living_plant_count.toLocaleString()}</td>
                <td className="p-3 text-ink">
                  {s.last_harvest_effective_time ? new Date(s.last_harvest_effective_time).toLocaleDateString() : "—"}
                </td>
                <td className="p-3">
                  {isSelected ? (
                    <Button type="button" variant="secondary" onClick={() => onRemove(s.gutter_id)}>
                      Remove
                    </Button>
                  ) : (
                    <Button
                      type="button" variant="primary" disabled={s.quality_hold_open || isWrongBatch}
                      onClick={() => onAdd(s)}
                    >
                      Add
                    </Button>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
