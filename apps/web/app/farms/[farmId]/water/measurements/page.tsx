"use client";

import { useParams } from "next/navigation";
import { useMemo, useState } from "react";

import { Breadcrumbs } from "@/components/Breadcrumbs";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { LoadingSkeleton } from "@/components/LoadingSkeleton";
import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/components/ui/Button";
import {
  tableBodyDividerClass, tableHeadRowClass, tableRowHoverClass, tableTdClass, tableThClass, tableWrapperClass,
} from "@/components/ui/table";
import { WaterSubNav } from "@/components/water/WaterSubNav";
import type { WaterMeasurementCreate } from "@/lib/api/client";
import { AppError } from "@/lib/errors/adapter";
import { formatDateTimeWithZoneLabel } from "@/lib/format/datetime";
import { humanizeEnumCode } from "@/lib/format/humanize";
import {
  useAssets,
  useCalibrationStatus,
  useFarm,
  useIrrigationCircuits,
  useMeasurementsForFarm,
  useRecordMeasurement,
  useReservoirs,
  useSamplingPoints,
  useWaterInstruments,
  useWaterReturnPoints,
  useWaterSources,
} from "@/lib/query/hooks";

function errorMessage(error: unknown): string {
  return error instanceof AppError ? error.message : "Something went wrong. Please try again.";
}

const inputClass =
  "min-h-10 w-full rounded-md border border-wl-border bg-wl-surface-raised px-3 text-sm text-wl-text focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-wl-focus";
const labelClass = "flex flex-col gap-1 text-sm";
const labelTextClass = "text-xs font-medium uppercase tracking-wide text-wl-text-secondary";

// PILOT-WATER-001A canonical metric set (app/models/water_measurement.py) --
// never invent a fifth metric or a combined "worksheet" aggregate model.
// Each row here becomes, at most, one independent WaterMeasurement record.
const METRICS = [
  { metric: "PH", label: "pH", unit: "pH", supportsFlag: "supports_ph" as const },
  { metric: "EC", label: "EC", unit: "mS/cm", supportsFlag: "supports_ec" as const },
  { metric: "SOLUTION_TEMPERATURE", label: "Solution Temp", unit: "°C", supportsFlag: "supports_solution_temperature" as const },
  { metric: "DISSOLVED_OXYGEN", label: "Dissolved Oxygen", unit: "mg/L", supportsFlag: "supports_dissolved_oxygen" as const },
];

type CalibrationStatusShape = {
  latest_by_metric?: Record<string, { effective_at: string; result: string; standard_reference: string | null }>;
};

function CalibrationHint({ instrumentId, metric }: { instrumentId: string | undefined; metric: string }) {
  const statusQuery = useCalibrationStatus(instrumentId);
  if (!instrumentId) return null;
  if (statusQuery.isLoading) return <span className="text-xs text-wl-text-tertiary">Checking calibration…</span>;
  if (statusQuery.isError) return <span className="text-xs text-wl-text-tertiary">Calibration status unknown</span>;
  const status = statusQuery.data as CalibrationStatusShape | undefined;
  const entry = status?.latest_by_metric?.[metric];
  if (!entry) return <span className="text-xs text-wl-hold-fg">Calibration status unknown for {humanizeEnumCode(metric)}</span>;
  return (
    <span className="text-xs text-wl-text-tertiary">
      Last calibrated: {formatDateTimeWithZoneLabel(entry.effective_at)} ({entry.result})
    </span>
  );
}

/** PILOT-WATER-001B: fast multi-metric worksheet -- one Sampling Point,
 * then up to four independent metric rows (pH/EC/Temp/DO). Submitting
 * creates exactly one WaterMeasurement per row the operator actually
 * filled in; a blank row is never submitted as a fabricated 0/empty
 * reading. */
export function MeasurementWorksheet({ farmId }: { farmId: string }) {
  const samplingPointsQuery = useSamplingPoints(farmId);
  const sourcesQuery = useWaterSources(farmId);
  const reservoirsQuery = useReservoirs(farmId);
  const circuitsQuery = useIrrigationCircuits(farmId);
  const returnPointsQuery = useWaterReturnPoints(farmId);
  const instrumentsQuery = useWaterInstruments(farmId);
  const assetsQuery = useAssets(farmId, "water_quality_meter");

  const [samplingPointId, setSamplingPointId] = useState("");
  const [values, setValues] = useState<Record<string, string>>({});
  const [instrumentByMetric, setInstrumentByMetric] = useState<Record<string, string>>({});
  const [notes, setNotes] = useState("");
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [submitCount, setSubmitCount] = useState(0);

  const recordMeasurement = useRecordMeasurement(farmId, samplingPointId);

  const samplingPoint = (samplingPointsQuery.data ?? []).find((p) => p.id === samplingPointId);
  const assetCodeById = new Map((assetsQuery.data ?? []).map((a) => [a.id, `${a.code} — ${a.name}`]));

  const contextLabel = useMemo(() => {
    if (!samplingPoint) return null;
    const source = (sourcesQuery.data ?? []).find((s) => s.id === samplingPoint.water_source_id);
    const reservoir = (reservoirsQuery.data ?? []).find((r) => r.id === samplingPoint.reservoir_id);
    const circuit = (circuitsQuery.data ?? []).find((c) => c.id === samplingPoint.irrigation_circuit_id);
    const returnPoint = (returnPointsQuery.data ?? []).find((r) => r.id === samplingPoint.water_return_point_id);
    if (source) return `Water Source: ${source.code} — ${source.name}`;
    if (reservoir) return `Reservoir/Tank: ${reservoir.code} — ${reservoir.name}`;
    if (circuit) return `Irrigation Circuit: ${circuit.code} — ${circuit.name}`;
    if (returnPoint) return `Return/Drain Point: ${returnPoint.code} — ${returnPoint.name}`;
    return "Other water context (no anchored entity)";
  }, [samplingPoint, sourcesQuery.data, reservoirsQuery.data, circuitsQuery.data, returnPointsQuery.data]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitError(null);
    if (!samplingPointId) {
      setSubmitError("Choose a Sampling Point first.");
      return;
    }
    const rowsToSubmit = METRICS.filter((m) => values[m.metric]?.trim());
    if (rowsToSubmit.length === 0) {
      setSubmitError("Enter at least one metric value.");
      return;
    }
    try {
      for (const row of rowsToSubmit) {
        const payload: WaterMeasurementCreate = {
          metric: row.metric,
          value: values[row.metric].trim(),
          unit: row.unit,
          water_instrument_id: instrumentByMetric[row.metric] || null,
          notes: notes.trim() || null,
          client_command_id: crypto.randomUUID(),
        };
        // Each metric row is its own independent WaterMeasurement command;
        // sequential keeps idempotency keys and error attribution per-row simple.
        await recordMeasurement.mutateAsync(payload);
      }
      setValues({});
      setInstrumentByMetric({});
      setNotes("");
      setSubmitCount((n) => n + 1);
    } catch (err) {
      setSubmitError(errorMessage(err));
    }
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-4 rounded-xl border border-wl-border bg-wl-surface-raised p-4">
      <label className={labelClass}>
        <span className={labelTextClass}>Sampling Point</span>
        <select
          className={inputClass}
          value={samplingPointId}
          onChange={(e) => setSamplingPointId(e.target.value)}
          required
        >
          <option value="">Select a Sampling Point…</option>
          {(samplingPointsQuery.data ?? []).map((p) => (
            <option key={p.id} value={p.id}>
              {p.code} — {p.name} ({humanizeEnumCode(p.point_type)})
            </option>
          ))}
        </select>
      </label>
      {samplingPoint && <p className="text-xs text-wl-text-secondary">{contextLabel}</p>}

      <div className="flex flex-col gap-3">
        {METRICS.map((m) => {
          const eligibleInstruments = (instrumentsQuery.data ?? []).filter((i) => i[m.supportsFlag] && i.status === "active");
          return (
            <div key={m.metric} className="grid grid-cols-1 gap-2 border-t border-wl-border pt-3 first:border-t-0 first:pt-0 md:grid-cols-[1fr_1fr_2fr]">
              <label className={labelClass}>
                <span className={labelTextClass}>{m.label} ({m.unit})</span>
                <input
                  type="number"
                  step="any"
                  className={inputClass}
                  value={values[m.metric] ?? ""}
                  onChange={(e) => setValues((v) => ({ ...v, [m.metric]: e.target.value }))}
                  placeholder="Leave blank to skip"
                />
              </label>
              <label className={labelClass}>
                <span className={labelTextClass}>Instrument</span>
                <select
                  className={inputClass}
                  value={instrumentByMetric[m.metric] ?? ""}
                  onChange={(e) => setInstrumentByMetric((v) => ({ ...v, [m.metric]: e.target.value }))}
                >
                  <option value="">No instrument recorded</option>
                  {eligibleInstruments.map((i) => (
                    <option key={i.id} value={i.id}>
                      {assetCodeById.get(i.asset_id) ?? i.asset_id}
                    </option>
                  ))}
                </select>
              </label>
              <div className="flex items-end">
                <CalibrationHint instrumentId={instrumentByMetric[m.metric] || undefined} metric={m.metric} />
              </div>
            </div>
          );
        })}
      </div>

      <label className={labelClass}>
        <span className={labelTextClass}>Notes (optional, applies to all rows submitted)</span>
        <textarea className={`${inputClass} min-h-20`} value={notes} onChange={(e) => setNotes(e.target.value)} />
      </label>

      {submitError && <p className="text-xs text-wl-flag-fg">{submitError}</p>}
      {submitCount > 0 && !submitError && (
        <p className="text-xs text-wl-grow-fg">Measurements recorded.</p>
      )}

      <Button type="submit" disabled={recordMeasurement.isPending}>
        {recordMeasurement.isPending ? "Recording…" : "Record Measurements"}
      </Button>
    </form>
  );
}

const HISTORY_METRIC_OPTIONS = ["", ...METRICS.map((m) => m.metric)];

function MeasurementHistory({ farmId }: { farmId: string }) {
  const [metric, setMetric] = useState("");
  const [reservoirId, setReservoirId] = useState("");
  const [windowStart, setWindowStart] = useState("");
  const [windowEnd, setWindowEnd] = useState("");

  const reservoirsQuery = useReservoirs(farmId);
  const samplingPointsQuery = useSamplingPoints(farmId);
  const historyQuery = useMeasurementsForFarm(farmId, {
    metric: metric || undefined,
    reservoirId: reservoirId || undefined,
    windowStart: windowStart ? new Date(windowStart).toISOString() : undefined,
    windowEnd: windowEnd ? new Date(windowEnd).toISOString() : undefined,
  });

  const samplingPointById = new Map((samplingPointsQuery.data ?? []).map((p) => [p.id, p]));
  const rows = [...(historyQuery.data ?? [])].sort(
    (a, b) => new Date(b.effective_at).getTime() - new Date(a.effective_at).getTime(),
  );

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-end gap-3">
        <label className={labelClass}>
          <span className={labelTextClass}>Metric</span>
          <select className={inputClass} value={metric} onChange={(e) => setMetric(e.target.value)}>
            {HISTORY_METRIC_OPTIONS.map((m) => (
              <option key={m || "all"} value={m}>
                {m ? humanizeEnumCode(m) : "All metrics"}
              </option>
            ))}
          </select>
        </label>
        <label className={labelClass}>
          <span className={labelTextClass}>Reservoir / Tank</span>
          <select className={inputClass} value={reservoirId} onChange={(e) => setReservoirId(e.target.value)}>
            <option value="">All reservoirs</option>
            {(reservoirsQuery.data ?? []).map((r) => (
              <option key={r.id} value={r.id}>{r.code} — {r.name}</option>
            ))}
          </select>
        </label>
        <label className={labelClass}>
          <span className={labelTextClass}>From</span>
          <input type="datetime-local" className={inputClass} value={windowStart} onChange={(e) => setWindowStart(e.target.value)} />
        </label>
        <label className={labelClass}>
          <span className={labelTextClass}>To</span>
          <input type="datetime-local" className={inputClass} value={windowEnd} onChange={(e) => setWindowEnd(e.target.value)} />
        </label>
      </div>

      {historyQuery.isLoading && !historyQuery.data ? (
        <LoadingSkeleton rows={4} label="Loading measurement history" />
      ) : historyQuery.isError && !historyQuery.data ? (
        <ErrorState error={historyQuery.error} onRetry={() => historyQuery.refetch()} />
      ) : rows.length === 0 ? (
        <EmptyState title="No measurements match these filters" />
      ) : (
        <div className={tableWrapperClass}>
          <table className="w-full text-sm">
            <thead>
              <tr className={tableHeadRowClass}>
                <th className={tableThClass}>Sampling Point</th>
                <th className={tableThClass}>Metric</th>
                <th className={`${tableThClass} text-right`}>Value</th>
                <th className={tableThClass}>Effective</th>
                <th className={tableThClass}>Recorded</th>
                <th className={tableThClass}>Notes</th>
              </tr>
            </thead>
            <tbody className={tableBodyDividerClass}>
              {rows.map((m) => {
                const point = samplingPointById.get(m.sampling_point_id);
                return (
                  <tr key={m.id} className={tableRowHoverClass}>
                    <td className={tableTdClass}>{point ? `${point.code} — ${point.name}` : m.sampling_point_id.slice(0, 8)}</td>
                    <td className={tableTdClass}>{humanizeEnumCode(m.metric)}</td>
                    <td className={`${tableTdClass} text-right tabular-nums`}>{m.value} {m.unit}</td>
                    <td className={tableTdClass}>{formatDateTimeWithZoneLabel(m.effective_at)}</td>
                    <td className={tableTdClass}>{formatDateTimeWithZoneLabel(m.recorded_at)}</td>
                    <td className={tableTdClass}>{m.notes ?? "—"}</td>
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

export default function WaterMeasurementsPage() {
  const { farmId } = useParams<{ farmId: string }>();
  const { data: farm } = useFarm(farmId);

  return (
    <div>
      <PageHeader
        title="Measurements"
        description={farm ? `Record pH/EC/temperature/DO readings for ${farm.name}` : "Record water readings"}
        breadcrumbs={
          <Breadcrumbs items={[
            { label: "Home", href: `/farms/${farmId}` },
            { label: "Water & Nutrients", href: `/farms/${farmId}/water` },
            { label: "Measurements" },
          ]}
          />
        }
      />
      <WaterSubNav farmId={farmId} />

      <section className="flex flex-col gap-2">
        <h2 className="font-serif text-base font-semibold text-wl-text">Record Measurements</h2>
        <MeasurementWorksheet farmId={farmId} />
      </section>

      <section className="mt-6 flex flex-col gap-2">
        <h2 className="font-serif text-base font-semibold text-wl-text">Measurement History</h2>
        <MeasurementHistory farmId={farmId} />
      </section>
    </div>
  );
}
