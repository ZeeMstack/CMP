"use client";

import { useParams } from "next/navigation";
import { useState } from "react";

import { Breadcrumbs } from "@/components/Breadcrumbs";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { LoadingSkeleton } from "@/components/LoadingSkeleton";
import { PageHeader } from "@/components/PageHeader";
import { StatusBadge } from "@/components/StatusBadge";
import {
  tableBodyDividerClass, tableHeadRowClass, tableRowHoverClass, tableTdClass, tableThClass, tableWrapperClass,
} from "@/components/ui/table";
import { WaterSubNav } from "@/components/water/WaterSubNav";
import { formatDateTimeWithZoneLabel } from "@/lib/format/datetime";
import {
  useExposedPlacementsForCircuit,
  useExposedPlacementsForReservoir,
  useBatchWaterExposure,
  useFarm,
  useIrrigationCircuits,
  useOperationalSummary,
  useReservoirs,
} from "@/lib/query/hooks";

const inputClass =
  "min-h-10 w-full rounded-md border border-wl-border bg-wl-surface-raised px-3 text-sm text-wl-text focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-wl-focus";
const labelClass = "flex flex-col gap-1 text-sm";
const labelTextClass = "text-xs font-medium uppercase tracking-wide text-wl-text-secondary";

/** PILOT-WATER-001B evidence wording (frozen, from WATER-001A): never
 * "Affected/Contaminated/Infected Crops" -- exposure is traceability
 * evidence, distinguishing what was actually recorded delivered from what
 * the current/historical topology merely makes possible. */
export function exposureKindLabel(kind: string): string {
  if (kind === "RECORDED_DELIVERY_EXPOSURE") return "Recorded Delivery Exposure";
  if (kind === "CONFIGURED_TOPOLOGY_EXPOSURE") return "Configured Topology Exposure";
  return kind;
}
function exposureKindTone(kind: string): "active" | "neutral" {
  return kind === "RECORDED_DELIVERY_EXPOSURE" ? "active" : "neutral";
}

function toIsoOrUndefined(local: string): string | undefined {
  return local ? new Date(local).toISOString() : undefined;
}

/** Crop-centric view: a Batch's Water Exposure History over a window --
 * which Circuits/Reservoirs it may have received water from, and on what
 * evidence. Never implies exposure from shared Farm membership alone; this
 * is exactly the read model WATER-001A built for that reason. */
function BatchCentricView({ farmId }: { farmId: string }) {
  const batchesQuery = useOperationalSummary(farmId, "all");
  const [batchId, setBatchId] = useState("");
  const [windowStart, setWindowStart] = useState("");
  const [windowEnd, setWindowEnd] = useState("");

  const start = toIsoOrUndefined(windowStart);
  const end = toIsoOrUndefined(windowEnd);
  const exposureQuery = useBatchWaterExposure(farmId, batchId || undefined, start, end);
  const circuitsQuery = useIrrigationCircuits(farmId);
  const reservoirsQuery = useReservoirs(farmId);
  const circuitById = new Map((circuitsQuery.data ?? []).map((c) => [c.id, c]));
  const reservoirById = new Map((reservoirsQuery.data ?? []).map((r) => [r.id, r]));

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-end gap-3">
        <label className={labelClass}>
          <span className={labelTextClass}>Batch</span>
          <select className={inputClass} value={batchId} onChange={(e) => setBatchId(e.target.value)}>
            <option value="">Select a Batch…</option>
            {(batchesQuery.data ?? []).map((b) => (
              <option key={b.id} value={b.id}>{b.code}</option>
            ))}
          </select>
        </label>
        <label className={labelClass}>
          <span className={labelTextClass}>Window Start</span>
          <input type="datetime-local" className={inputClass} value={windowStart} onChange={(e) => setWindowStart(e.target.value)} />
        </label>
        <label className={labelClass}>
          <span className={labelTextClass}>Window End</span>
          <input type="datetime-local" className={inputClass} value={windowEnd} onChange={(e) => setWindowEnd(e.target.value)} />
        </label>
      </div>

      {!batchId || !start || !end ? (
        <p className="text-sm text-wl-text-tertiary">Choose a Batch and a window (start and end) to see potential water exposure.</p>
      ) : exposureQuery.isLoading && !exposureQuery.data ? (
        <LoadingSkeleton rows={3} label="Loading water exposure" />
      ) : exposureQuery.isError && !exposureQuery.data ? (
        <ErrorState error={exposureQuery.error} onRetry={() => exposureQuery.refetch()} />
      ) : (exposureQuery.data ?? []).length === 0 ? (
        <EmptyState title="No potentially exposed water evidence in this window" />
      ) : (
        <div className={tableWrapperClass}>
          <table className="w-full text-sm">
            <thead>
              <tr className={tableHeadRowClass}>
                <th className={tableThClass}>Irrigation Circuit</th>
                <th className={tableThClass}>Reservoirs</th>
                <th className={tableThClass}>Locations</th>
                <th className={tableThClass}>Evidence</th>
              </tr>
            </thead>
            <tbody className={tableBodyDividerClass}>
              {(exposureQuery.data ?? []).map((row, i) => {
                const circuit = circuitById.get(row.irrigation_circuit_id);
                return (
                  <tr key={i} className={tableRowHoverClass}>
                    <td className={tableTdClass}>{circuit ? `${circuit.code} — ${circuit.name}` : row.irrigation_circuit_id.slice(0, 8)}</td>
                    <td className={tableTdClass}>
                      {row.reservoir_ids.map((id) => reservoirById.get(id)?.code ?? id.slice(0, 8)).join(", ")}
                    </td>
                    <td className={tableTdClass}>{row.location_ids.length} Location(s)</td>
                    <td className={tableTdClass}>
                      <StatusBadge label={exposureKindLabel(row.exposure_kind)} tone={exposureKindTone(row.exposure_kind)} />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

/** Water-centric view: given a Reservoir or Circuit and a window, which
 * Batch Placements were potentially exposed -- the reverse direction of
 * the same evidence, driven by actual topology + recorded delivery, never
 * by Farm membership. */
function WaterCentricView({ farmId }: { farmId: string }) {
  const reservoirsQuery = useReservoirs(farmId);
  const circuitsQuery = useIrrigationCircuits(farmId);
  const [mode, setMode] = useState<"reservoir" | "circuit">("reservoir");
  const [entityId, setEntityId] = useState("");
  const [windowStart, setWindowStart] = useState("");
  const [windowEnd, setWindowEnd] = useState("");

  const start = toIsoOrUndefined(windowStart);
  const end = toIsoOrUndefined(windowEnd);
  const reservoirExposureQuery = useExposedPlacementsForReservoir(
    farmId, mode === "reservoir" ? entityId || undefined : undefined, start, end,
  );
  const circuitExposureQuery = useExposedPlacementsForCircuit(
    farmId, mode === "circuit" ? entityId || undefined : undefined, start, end,
  );
  const activeQuery = mode === "reservoir" ? reservoirExposureQuery : circuitExposureQuery;

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-end gap-3">
        <label className={labelClass}>
          <span className={labelTextClass}>Look up by</span>
          <select className={inputClass} value={mode} onChange={(e) => { setMode(e.target.value as "reservoir" | "circuit"); setEntityId(""); }}>
            <option value="reservoir">Reservoir / Tank</option>
            <option value="circuit">Irrigation Circuit</option>
          </select>
        </label>
        <label className={labelClass}>
          <span className={labelTextClass}>{mode === "reservoir" ? "Reservoir / Tank" : "Irrigation Circuit"}</span>
          <select className={inputClass} value={entityId} onChange={(e) => setEntityId(e.target.value)}>
            <option value="">Select…</option>
            {mode === "reservoir"
              ? (reservoirsQuery.data ?? []).map((r) => <option key={r.id} value={r.id}>{r.code} — {r.name}</option>)
              : (circuitsQuery.data ?? []).map((c) => <option key={c.id} value={c.id}>{c.code} — {c.name}</option>)}
          </select>
        </label>
        <label className={labelClass}>
          <span className={labelTextClass}>Window Start</span>
          <input type="datetime-local" className={inputClass} value={windowStart} onChange={(e) => setWindowStart(e.target.value)} />
        </label>
        <label className={labelClass}>
          <span className={labelTextClass}>Window End</span>
          <input type="datetime-local" className={inputClass} value={windowEnd} onChange={(e) => setWindowEnd(e.target.value)} />
        </label>
      </div>

      {!entityId || !start || !end ? (
        <p className="text-sm text-wl-text-tertiary">Choose an entity and a window (start and end) to see potentially exposed Batch Placements.</p>
      ) : activeQuery.isLoading && !activeQuery.data ? (
        <LoadingSkeleton rows={3} label="Loading exposed placements" />
      ) : activeQuery.isError && !activeQuery.data ? (
        <ErrorState error={activeQuery.error} onRetry={() => activeQuery.refetch()} />
      ) : (activeQuery.data ?? []).length === 0 ? (
        <EmptyState title="No potentially exposed crop placements in this window" />
      ) : (
        <div className={tableWrapperClass}>
          <table className="w-full text-sm">
            <thead>
              <tr className={tableHeadRowClass}>
                <th className={tableThClass}>Batch</th>
                <th className={tableThClass}>Carrier</th>
                <th className={tableThClass}>Overlap</th>
                <th className={tableThClass}>Evidence</th>
              </tr>
            </thead>
            <tbody className={tableBodyDividerClass}>
              {(activeQuery.data ?? []).map((p, i) => (
                <tr key={i} className={tableRowHoverClass}>
                  <td className={tableTdClass}>{p.batch_id.slice(0, 8)}</td>
                  <td className={tableTdClass}>{p.carrier_id.slice(0, 8)}</td>
                  <td className={tableTdClass}>
                    {formatDateTimeWithZoneLabel(p.overlap_start)} – {formatDateTimeWithZoneLabel(p.overlap_end)}
                  </td>
                  <td className={tableTdClass}>
                    <StatusBadge label={exposureKindLabel(p.exposure_kind)} tone={exposureKindTone(p.exposure_kind)} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

/** PILOT-WATER-001B: Water Exposure Traceability -- two independent views
 * of the same evidence (WATER-001A `water_exposure_service`), never a
 * "disease/contaminated" framing. "Potentially exposed crop placements" is
 * the preferred, deliberately hedged wording. */
export default function WaterExposurePage() {
  const { farmId } = useParams<{ farmId: string }>();
  const { data: farm } = useFarm(farmId);
  const [view, setView] = useState<"batch" | "water">("batch");

  return (
    <div>
      <PageHeader
        title="Exposure"
        description={farm ? `Water exposure traceability for ${farm.name}` : "Water exposure traceability"}
        breadcrumbs={
          <Breadcrumbs items={[
            { label: "Home", href: `/farms/${farmId}` },
            { label: "Water & Nutrients", href: `/farms/${farmId}/water` },
            { label: "Exposure" },
          ]}
          />
        }
      />
      <WaterSubNav farmId={farmId} />

      <p className="mb-4 text-xs text-wl-text-tertiary">
        Exposure is traceability evidence only, based on actual topology connections and recorded deliveries -- never a
        disease or health claim, and never inferred merely because a Reservoir or Circuit shares Farm membership with a
        greenhouse it does not actually serve.
      </p>

      <nav className="mb-4 flex gap-4 border-b border-wl-border">
        {(["batch", "water"] as const).map((v) => (
          <button
            key={v}
            type="button"
            onClick={() => setView(v)}
            className={`-mb-px border-b-2 px-1 pb-2 text-sm font-medium ${
              view === v ? "border-wl-brand text-wl-brand" : "border-transparent text-wl-text-secondary hover:text-wl-text"
            }`}
          >
            {v === "batch" ? "By Batch" : "By Reservoir / Circuit"}
          </button>
        ))}
      </nav>

      {view === "batch" ? <BatchCentricView farmId={farmId} /> : <WaterCentricView farmId={farmId} />}
    </div>
  );
}
