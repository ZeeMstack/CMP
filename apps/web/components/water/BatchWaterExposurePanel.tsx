"use client";

import { useState } from "react";

import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { LoadingSkeleton } from "@/components/LoadingSkeleton";
import { StatusBadge } from "@/components/StatusBadge";
import type { CropBatchRead } from "@/lib/api/client";
import { useBatchWaterExposure, useIrrigationCircuits, useReservoirs } from "@/lib/query/hooks";

const inputClass =
  "min-h-9 rounded-md border border-wl-border bg-wl-surface-raised px-2 text-sm text-wl-text focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-wl-focus";

function exposureKindLabel(kind: string): string {
  if (kind === "RECORDED_DELIVERY_EXPOSURE") return "Recorded Delivery Exposure";
  if (kind === "CONFIGURED_TOPOLOGY_EXPOSURE") return "Configured Topology Exposure";
  return kind;
}
function exposureKindTone(kind: string): "active" | "neutral" {
  return kind === "RECORDED_DELIVERY_EXPOSURE" ? "active" : "neutral";
}

function defaultWindow(): { start: string; end: string } {
  const end = new Date();
  const start = new Date(end.getTime() - 14 * 24 * 60 * 60 * 1000);
  const toLocal = (d: Date) => d.toISOString().slice(0, 16);
  return { start: toLocal(start), end: toLocal(end) };
}

/** PILOT-WATER-001B: compact Water Exposure section for the Batch detail
 * page -- Tank/Circuit/period/evidence type only, never a full water
 * dashboard. Uses WATER-001A's own read model (`useBatchWaterExposure`);
 * never infers exposure itself. Defaults to a trailing 14-day window,
 * operator-adjustable. */
export function BatchWaterExposurePanel({ farmId, batch }: { farmId: string; batch: CropBatchRead }) {
  const [win, setWin] = useState(defaultWindow());
  const start = win.start ? new Date(win.start).toISOString() : undefined;
  const end = win.end ? new Date(win.end).toISOString() : undefined;

  const exposureQuery = useBatchWaterExposure(farmId, batch.id, start, end);
  const circuitsQuery = useIrrigationCircuits(farmId);
  const reservoirsQuery = useReservoirs(farmId);
  const circuitById = new Map((circuitsQuery.data ?? []).map((c) => [c.id, c]));
  const reservoirById = new Map((reservoirsQuery.data ?? []).map((r) => [r.id, r]));

  return (
    <div className="flex flex-col gap-3">
      <p className="text-xs text-wl-text-secondary">
        Potentially exposed Circuits/Reservoirs over a window, based on actual topology and recorded deliveries -- never a
        disease or health claim.
      </p>
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <label className="flex items-center gap-1">
          From
          <input type="datetime-local" className={inputClass} value={win.start} onChange={(e) => setWin((w) => ({ ...w, start: e.target.value }))} />
        </label>
        <label className="flex items-center gap-1">
          To
          <input type="datetime-local" className={inputClass} value={win.end} onChange={(e) => setWin((w) => ({ ...w, end: e.target.value }))} />
        </label>
      </div>

      {exposureQuery.isLoading && !exposureQuery.data ? (
        <LoadingSkeleton rows={2} label="Loading water exposure" />
      ) : exposureQuery.isError && !exposureQuery.data ? (
        <ErrorState error={exposureQuery.error} onRetry={() => exposureQuery.refetch()} />
      ) : (exposureQuery.data ?? []).length === 0 ? (
        <EmptyState title="No potentially exposed water evidence in this window" />
      ) : (
        <ul className="flex flex-col gap-2">
          {(exposureQuery.data ?? []).map((row, i) => {
            const circuit = circuitById.get(row.irrigation_circuit_id);
            return (
              <li key={i} className="rounded-lg border border-wl-border bg-wl-surface-raised p-3 text-sm">
                <div className="flex items-center justify-between gap-2">
                  <span className="font-medium text-wl-text">{circuit ? `${circuit.code} — ${circuit.name}` : row.irrigation_circuit_id.slice(0, 8)}</span>
                  <StatusBadge label={exposureKindLabel(row.exposure_kind)} tone={exposureKindTone(row.exposure_kind)} />
                </div>
                <p className="mt-1 text-xs text-wl-text-secondary">
                  Tank(s): {row.reservoir_ids.map((id) => reservoirById.get(id)?.code ?? id.slice(0, 8)).join(", ")} ·{" "}
                  {row.location_ids.length} Location(s)
                </p>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
