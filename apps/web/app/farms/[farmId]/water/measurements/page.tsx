"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useMemo, useState } from "react";

import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { LoadingSkeleton } from "@/components/LoadingSkeleton";
import { StatusBadge, type StatusTone } from "@/components/StatusBadge";
import { BoundedDataRegion } from "@/components/layout/BoundedDataRegion";
import { ContextStrip, ContextStripItem } from "@/components/layout/ContextStrip";
import { SplitWorkspace } from "@/components/layout/SplitWorkspace";
import { StickyActionBar } from "@/components/layout/StickyActionBar";
import { ViewTabs } from "@/components/layout/ViewTabs";
import { Button } from "@/components/ui/Button";
import {
  BlockerList,
  Fact,
  FactList,
  TimingField,
  WATER_METRICS,
  WaterWorkspaceHeader,
  cardClass,
  commandErrorLine,
  entityLabel,
  inputClass,
  labelClass,
  labelTextClass,
  linkButtonClass,
  localInputToIso,
  stepLabelClass,
  type TimingMode,
} from "@/components/water/waterUi";
import {
  buildMeasurementRun,
  useMeasurementRun,
  type MeasurementRowStatus,
  type MeasurementRun,
  type MeasurementRunRow,
} from "@/components/water/useMeasurementRun";
import type { SamplingPointRead, WaterMeasurementRead } from "@/lib/api/client";
import { useReportCommandLocked } from "@/lib/commands/frozenSubmission";
import { formatDateTimeWithZoneLabel } from "@/lib/format/datetime";
import { humanizeEnumCode } from "@/lib/format/humanize";
import { useViewState } from "@/lib/navigation/useViewState";
import {
  useAssets,
  useCalibrationStatus,
  useFarm,
  useIrrigationCircuits,
  useMeasurementsForFarm,
  useRecordMeasurement,
  useReservoirs,
  useSamplingPoints,
  useWaterDeliveryPoints,
  useWaterInstruments,
  useWaterReturnPoints,
  useWaterSources,
} from "@/lib/query/hooks";

const METRICS = WATER_METRICS;

const VIEWS = ["record", "history"] as const;
type View = (typeof VIEWS)[number];

type CalibrationStatusShape = {
  latest_by_metric?: Record<string, { effective_at: string; result: string; standard_reference: string | null }>;
};

/** Supporting evidence only -- never blocks recording, and a missing or
 * failed status stays "unknown" (never implied from a Measurement). */
function CalibrationHint({ instrumentId, metric }: { instrumentId: string | undefined; metric: string }) {
  const statusQuery = useCalibrationStatus(instrumentId);
  if (!instrumentId) return <span className="text-xs text-wl-text-tertiary">—</span>;
  if (statusQuery.isLoading) return <span className="text-xs text-wl-text-tertiary">Checking…</span>;
  if (statusQuery.isError) return <span className="text-xs text-wl-text-tertiary">Calibration status unavailable</span>;
  const entry = (statusQuery.data as CalibrationStatusShape | undefined)?.latest_by_metric?.[metric];
  if (!entry) return <span className="text-xs text-wl-hold-fg">Calibration unknown</span>;
  return (
    <span className="text-xs text-wl-text-tertiary">
      Last calibrated {formatDateTimeWithZoneLabel(entry.effective_at)} ({humanizeEnumCode(entry.result)})
    </span>
  );
}

/** Human-readable anchor context for a Sampling Point: Source, Reservoir/
 * Tank, Circuit, Delivery Point, or Return/Drain Point. */
function useSamplingPointContext(farmId: string) {
  const sources = useWaterSources(farmId).data ?? [];
  const reservoirs = useReservoirs(farmId).data ?? [];
  const circuits = useIrrigationCircuits(farmId).data ?? [];
  const deliveryPoints = useWaterDeliveryPoints(farmId).data ?? [];
  const returnPoints = useWaterReturnPoints(farmId).data ?? [];
  return (point: SamplingPointRead | undefined): string => {
    if (!point) return "";
    const anchors: [string, string | null, { code: string; name: string }[]][] = [
      ["Water Source", point.water_source_id, sources],
      ["Reservoir / Tank", point.reservoir_id, reservoirs],
      ["Irrigation Circuit", point.irrigation_circuit_id, circuits],
      ["Delivery Point", point.water_delivery_point_id, deliveryPoints],
      ["Return / Drain Point", point.water_return_point_id, returnPoints],
    ];
    for (const [kind, id, rows] of anchors) {
      if (!id) continue;
      const row = (rows as ({ id: string } & { code: string; name: string })[]).find((r) => r.id === id);
      return `${kind}: ${entityLabel(row) ?? "label unavailable"}`;
    }
    return "Other water context (no anchored entity)";
  };
}

function useInstrumentLabels(farmId: string) {
  const instruments = useWaterInstruments(farmId);
  const assets = useAssets(farmId, "water_quality_meter");
  const assetById = new Map((assets.data ?? []).map((a) => [a.id, a]));
  const label = (instrumentId: string | null): string | null => {
    if (!instrumentId) return null;
    const instrument = (instruments.data ?? []).find((i) => i.id === instrumentId);
    const asset = instrument ? assetById.get(instrument.asset_id) : undefined;
    return entityLabel(asset) ?? "Instrument label unavailable";
  };
  return { instruments, label, assetById };
}

const STATUS_COPY: Record<MeasurementRowStatus, { label: string; tone: StatusTone }> = {
  not_sent: { label: "Not sent", tone: "neutral" },
  submitting: { label: "Submitting…", tone: "neutral" },
  confirmed: { label: "Confirmed", tone: "active" },
  uncertain: { label: "Unconfirmed — retry", tone: "attention" },
  rejected: { label: "Rejected", tone: "critical" },
};

function RunRowsTable({ rows }: { rows: MeasurementRunRow[] }) {
  return (
    <table className="w-full text-sm">
      <thead>
        <tr className="text-left text-xs text-wl-text-secondary">
          <th className="px-3 py-1.5 font-medium">Metric</th>
          <th className="px-3 py-1.5 font-medium">Value</th>
          <th className="hidden px-3 py-1.5 font-medium sm:table-cell">Instrument</th>
          <th className="px-3 py-1.5 font-medium">Status</th>
          <th className="hidden px-3 py-1.5 font-medium sm:table-cell">Effective (server)</th>
        </tr>
      </thead>
      <tbody className="divide-y divide-wl-border">
        {rows.map((row) => (
          <tr key={row.payload.client_command_id} data-testid={`run-row-${row.metric}`}>
            <td className="px-3 py-2 font-medium text-wl-text">{row.label}</td>
            <td className="px-3 py-2 tabular-nums">{row.payload.value} {row.payload.unit}</td>
            <td className="hidden px-3 py-2 text-xs sm:table-cell">{row.instrumentLabel ?? "No instrument recorded"}</td>
            <td className="px-3 py-2">
              <StatusBadge label={STATUS_COPY[row.status].label} tone={STATUS_COPY[row.status].tone} />
            </td>
            <td className="hidden px-3 py-2 text-xs sm:table-cell">
              {row.result ? formatDateTimeWithZoneLabel(row.result.effective_at) : "—"}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function ReceiptRows({ results }: { results: { label: string; result: WaterMeasurementRead }[] }) {
  return (
    <ul className="flex flex-col divide-y divide-wl-border rounded-lg border border-wl-border">
      {results.map(({ label, result }) => (
        <li key={result.id} className="flex flex-wrap items-baseline justify-between gap-2 px-3 py-2 text-sm">
          <span className="font-medium text-wl-text">
            {label}: {result.value} {result.unit}
          </span>
          <span className="text-xs text-wl-text-secondary">
            Effective {formatDateTimeWithZoneLabel(result.effective_at)} · ID{" "}
            <span className="font-mono">{result.id}</span>
          </span>
        </li>
      ))}
    </ul>
  );
}

type Draft = {
  samplingPointId: string;
  values: Record<string, string>;
  instruments: Record<string, string>;
  timingMode: TimingMode;
  customTime: string;
  notes: string;
};

const EMPTY_DRAFT: Draft = { samplingPointId: "", values: {}, instruments: {}, timingMode: "now", customTime: "", notes: "" };

/** Record view: Configure -> Review -> per-row run -> Receipt. The run (all
 * frozen commands) lives here, above anything a view/selection change
 * could unmount; the page keeps this component mounted across views. */
export function MeasurementRecorder({ farmId, onLockedChange }: { farmId: string; onLockedChange: (locked: boolean) => void }) {
  const samplingPointsQuery = useSamplingPoints(farmId);
  const contextFor = useSamplingPointContext(farmId);
  const { instruments, label: instrumentLabel } = useInstrumentLabels(farmId);
  const recordMeasurement = useRecordMeasurement(farmId);
  const measurementRun = useMeasurementRun((samplingPointId, payload) =>
    recordMeasurement.mutateAsync({ samplingPointId, payload }),
  );
  const { run, phase, locked } = measurementRun;

  useReportCommandLocked(locked ? "submitting" : "editing", onLockedChange);

  const [draft, setDraft] = useState<Draft>(EMPTY_DRAFT);
  const [step, setStep] = useState<"configure" | "review">("configure");
  const [formError, setFormError] = useState<string | null>(null);
  /** Rows confirmed by an earlier, partly rejected run -- kept visible as a
   * partial receipt, never erased or re-sent. */
  const [partialReceipt, setPartialReceipt] = useState<{ label: string; result: WaterMeasurementRead }[]>([]);

  const samplingPoints = samplingPointsQuery.data ?? [];
  const samplingPoint = samplingPoints.find((p) => p.id === draft.samplingPointId);
  const samplingPointLabel = samplingPoint
    ? `${entityLabel(samplingPoint)} (${humanizeEnumCode(samplingPoint.point_type)})`
    : "";

  const reviewRun = useMemo<MeasurementRun | null>(() => {
    if (step !== "review") return null;
    // Review shows exactly what Confirm will freeze -- ids are minted only
    // on Confirm (placeholder "" here).
    return buildMeasurementRun(
      {
        samplingPointId: draft.samplingPointId,
        samplingPointLabel,
        effectiveAt: draft.timingMode === "now" ? null : localInputToIso(draft.customTime),
        notes: draft.notes.trim() || null,
        rows: METRICS.map((m) => ({
          metric: m.metric, label: m.label, unit: m.unit, value: draft.values[m.metric] ?? "",
          instrumentId: draft.instruments[m.metric] || null,
          instrumentLabel: instrumentLabel(draft.instruments[m.metric] || null),
        })),
      },
      () => "",
    );
  }, [step, draft, samplingPointLabel, instrumentLabel]);

  function goToReview() {
    setFormError(null);
    if (!samplingPoint) return setFormError("Choose a Sampling Point first.");
    if (!METRICS.some((m) => (draft.values[m.metric] ?? "").trim() !== "")) {
      return setFormError("Enter at least one metric value. Blank rows are skipped, never recorded as zero.");
    }
    if (draft.timingMode === "custom") {
      const iso = localInputToIso(draft.customTime);
      if (!iso) return setFormError("Enter the custom time, or choose Now (server time).");
      if (new Date(iso).getTime() > Date.now()) return setFormError("The custom time cannot be in the future.");
    }
    setStep("review");
  }

  function confirm() {
    if (!reviewRun) return;
    // Frozen HERE: one payload + one command id per selected row.
    measurementRun.start({
      ...reviewRun,
      rows: reviewRun.rows.map((row) => ({
        ...row,
        payload: { ...row.payload, client_command_id: crypto.randomUUID() },
      })),
    });
    setStep("configure");
  }

  function returnUnsentToEdit() {
    if (!run) return;
    const confirmed = run.rows.filter((r) => r.status === "confirmed" && r.result);
    const unconfirmed = run.rows.filter((r) => r.status !== "confirmed");
    setPartialReceipt((prev) => [...prev, ...confirmed.map((r) => ({ label: r.label, result: r.result as WaterMeasurementRead }))]);
    setDraft((d) => ({
      ...d,
      values: Object.fromEntries(unconfirmed.map((r) => [r.metric, String(r.payload.value)])),
      instruments: Object.fromEntries(unconfirmed.map((r) => [r.metric, r.payload.water_instrument_id ?? ""])),
    }));
    measurementRun.clear();
  }

  function recordMore() {
    measurementRun.clear();
    setPartialReceipt([]);
    setDraft((d) => ({ ...EMPTY_DRAFT, samplingPointId: d.samplingPointId }));
  }

  // --- Run in progress / uncertain / rejected / complete --------------------------
  if (run && phase) {
    const confirmedRows = run.rows.filter((r) => r.status === "confirmed" && r.result);
    if (phase === "complete") {
      return (
        <section aria-label="Measurements receipt" className={`${cardClass} flex flex-col gap-3`}>
          <p role="status" className="text-sm font-semibold text-wl-grow-fg">
            Measurements recorded — {run.rows.length} of {run.rows.length} confirmed by the server.
          </p>
          <p className="text-xs text-wl-text-secondary">{run.samplingPointLabel}</p>
          <ReceiptRows
            results={[...partialReceipt, ...confirmedRows.map((r) => ({ label: r.label, result: r.result as WaterMeasurementRead }))]}
          />
          <div className="flex flex-wrap gap-2">
            <Button variant="primary" className="min-h-11" onClick={recordMore}>
              Record more measurements
            </Button>
            <Link href={`/farms/${farmId}/water/measurements?view=history`} className={linkButtonClass}>
              View history
            </Link>
          </div>
        </section>
      );
    }
    const uncertainRow = run.rows.find((r) => r.status === "uncertain");
    const rejectedRow = run.rows.find((r) => r.status === "rejected");
    return (
      <SplitWorkspace
        main={
          <section aria-label="Measurement commands" className={`${cardClass} flex flex-col gap-3`}>
            <h2 className="font-serif text-base font-semibold text-wl-text">Recording {run.rows.length} measurement(s)</h2>
            <FactList>
              <Fact label="Sampling Point">{run.samplingPointLabel}</Fact>
              <Fact label="Timing">
                {run.effectiveAt ? formatDateTimeWithZoneLabel(run.effectiveAt) : "Now (server time) — each row gets the server's time"}
              </Fact>
              <Fact label="Notes (every row)">{run.notes ?? "—"}</Fact>
            </FactList>
            <p className="text-xs text-wl-text-secondary">
              Each row is its own command, sent one at a time. A confirmed row is never sent again.
            </p>
            <RunRowsTable rows={run.rows} />
          </section>
        }
        rail={
          <section aria-label="Run status" className={`${cardClass} flex flex-col gap-3`}>
            <p className="text-sm font-semibold text-wl-text" role="status">
              {confirmedRows.length} of {run.rows.length} confirmed
            </p>
            {phase === "rejected" && confirmedRows.length > 0 && (
              <p className="text-xs text-wl-text-secondary">
                Partial result: the confirmed rows are recorded and stay recorded. Only the unconfirmed rows return to edit.
              </p>
            )}
            <StickyActionBar
              blockers={
                <BlockerList
                  lines={[
                    uncertainRow ? `${uncertainRow.label}: ${commandErrorLine(uncertainRow.error ?? null, true)}` : null,
                    rejectedRow ? `${rejectedRow.label}: ${commandErrorLine(rejectedRow.error ?? null, false)}` : null,
                  ]}
                />
              }
            >
              {phase === "rejected" ? (
                <Button variant="primary" className="min-h-11 w-full" onClick={returnUnsentToEdit}>
                  Return unconfirmed rows to edit
                </Button>
              ) : (
                <Button
                  variant="primary"
                  className="min-h-11 w-full"
                  onClick={() => void measurementRun.retry()}
                  disabled={phase !== "uncertain"}
                >
                  {phase === "uncertain" ? `Retry ${uncertainRow?.label ?? ""}` : "Recording…"}
                </Button>
              )}
            </StickyActionBar>
          </section>
        }
      />
    );
  }

  // --- Review ------------------------------------------------------------------------
  if (step === "review" && reviewRun) {
    return (
      <div>
        <p className={stepLabelClass}>Step 2 of 2 · Review</p>
        <SplitWorkspace
          main={
            <section aria-label="Review measurements" className={`${cardClass} flex flex-col gap-3`}>
              <h2 className="font-serif text-base font-semibold text-wl-text">Review before recording</h2>
              <FactList>
                <Fact label="Sampling Point">
                  {reviewRun.samplingPointLabel}
                  <span className="block text-xs text-wl-text-secondary">{contextFor(samplingPoint)}</span>
                </Fact>
                <Fact label="Timing">
                  {reviewRun.effectiveAt
                    ? `Custom: ${formatDateTimeWithZoneLabel(reviewRun.effectiveAt)} (every row)`
                    : "Now (server time) — the server assigns each row's time"}
                </Fact>
                <Fact label="Notes (every row)">{reviewRun.notes ?? "—"}</Fact>
              </FactList>
              <ul aria-label="Selected rows" className="divide-y divide-wl-border rounded-lg border border-wl-border">
                {reviewRun.rows.map((row) => (
                  <li key={row.metric} className="flex flex-wrap justify-between gap-2 px-3 py-2 text-sm">
                    <span className="font-medium text-wl-text">
                      {row.label}: {row.payload.value} {row.payload.unit}
                    </span>
                    <span className="text-xs text-wl-text-secondary">{row.instrumentLabel ?? "No instrument recorded"}</span>
                  </li>
                ))}
              </ul>
            </section>
          }
          rail={
            <section aria-label="Record summary" className={`${cardClass} flex flex-col gap-3`}>
              <p className="text-sm text-wl-text">
                {reviewRun.rows.length} independent measurement command(s). Blank metrics are not sent.
              </p>
              <StickyActionBar>
                <div className="flex gap-2">
                  <Button variant="secondary" className="min-h-11" onClick={() => setStep("configure")}>
                    Back to edit
                  </Button>
                  <Button variant="primary" className="min-h-11 flex-1" onClick={confirm}>
                    Record {reviewRun.rows.length} measurement(s)
                  </Button>
                </div>
              </StickyActionBar>
            </section>
          }
        />
      </div>
    );
  }

  // --- Configure ---------------------------------------------------------------------
  const filledCount = METRICS.filter((m) => (draft.values[m.metric] ?? "").trim() !== "").length;
  return (
    <div>
      <p className={stepLabelClass}>Step 1 of 2 · Configure</p>
      {partialReceipt.length > 0 && (
        <section aria-label="Already recorded" className="mb-3 flex flex-col gap-2 rounded-xl border border-wl-border bg-wl-grow-bg p-3">
          <p className="text-sm font-semibold text-wl-grow-fg">
            Partial result — these rows are recorded and will not be sent again:
          </p>
          <ReceiptRows results={partialReceipt} />
        </section>
      )}
      <SplitWorkspace
        main={
          <div className="flex min-w-0 flex-col gap-3">
            <ContextStrip>
              <ContextStripItem minWidth="16rem">
                <label className={labelClass}>
                  <span className={labelTextClass}>Sampling Point</span>
                  <select
                    className={inputClass}
                    value={draft.samplingPointId}
                    onChange={(e) => setDraft((d) => ({ ...d, samplingPointId: e.target.value }))}
                  >
                    <option value="">
                      {samplingPointsQuery.isLoading ? "Loading Sampling Points…" : "Select a Sampling Point…"}
                    </option>
                    {samplingPoints.map((p) => (
                      <option key={p.id} value={p.id}>
                        {entityLabel(p)} ({humanizeEnumCode(p.point_type)})
                      </option>
                    ))}
                  </select>
                </label>
              </ContextStripItem>
              <div className="flex flex-col gap-1">
                <span className={labelTextClass}>Anchored to</span>
                <span className="text-sm font-medium text-wl-text" data-testid="sampling-point-context">
                  {samplingPoint ? contextFor(samplingPoint) : "—"}
                </span>
              </div>
            </ContextStrip>
            {samplingPointsQuery.isError && (
              <ErrorState error={samplingPointsQuery.error} onRetry={() => samplingPointsQuery.refetch()} />
            )}

            <div className={`${cardClass} flex flex-col gap-2 p-3`}>
              <div className="hidden grid-cols-[minmax(8rem,1fr)_minmax(6rem,1fr)_4rem_minmax(10rem,1.5fr)_minmax(8rem,1.2fr)] gap-3 px-1 text-xs font-medium text-wl-text-secondary md:grid">
                <span>Metric</span>
                <span>Value</span>
                <span>Unit</span>
                <span>Instrument (optional)</span>
                <span>Calibration (evidence only)</span>
              </div>
              {METRICS.map((m) => {
                const eligible = (instruments.data ?? []).filter((i) => i[m.supportsFlag] && i.status === "active");
                const instrumentId = draft.instruments[m.metric] || undefined;
                return (
                  <div
                    key={m.metric}
                    className="grid grid-cols-2 items-center gap-2 border-t border-wl-border pt-2 first-of-type:border-t-0 md:grid-cols-[minmax(8rem,1fr)_minmax(6rem,1fr)_4rem_minmax(10rem,1.5fr)_minmax(8rem,1.2fr)] md:gap-3"
                  >
                    <label htmlFor={`value-${m.metric}`} className="col-span-2 text-sm font-medium text-wl-text md:col-span-1">
                      {m.label}
                    </label>
                    <input
                      id={`value-${m.metric}`}
                      type="number"
                      step="any"
                      inputMode="decimal"
                      aria-label={`${m.label} value (${m.unit})`}
                      className={inputClass}
                      value={draft.values[m.metric] ?? ""}
                      onChange={(e) => setDraft((d) => ({ ...d, values: { ...d.values, [m.metric]: e.target.value } }))}
                      placeholder="Blank = skip"
                    />
                    <span className="text-sm text-wl-text-secondary" aria-label={`${m.label} unit`}>
                      {m.unit}
                    </span>
                    <select
                      aria-label={`${m.label} instrument`}
                      className={`${inputClass} col-span-2 md:col-span-1`}
                      value={draft.instruments[m.metric] ?? ""}
                      onChange={(e) =>
                        setDraft((d) => ({ ...d, instruments: { ...d.instruments, [m.metric]: e.target.value } }))
                      }
                    >
                      <option value="">No instrument recorded</option>
                      {eligible.map((i) => (
                        <option key={i.id} value={i.id}>
                          {instrumentLabel(i.id)}
                        </option>
                      ))}
                    </select>
                    <div className="col-span-2 md:col-span-1">
                      <CalibrationHint instrumentId={instrumentId} metric={m.metric} />
                    </div>
                  </div>
                );
              })}
            </div>

            <div className={`${cardClass} grid grid-cols-1 gap-3 p-3 md:grid-cols-2`}>
              <TimingField
                legend="Effective time"
                mode={draft.timingMode}
                custom={draft.customTime}
                onModeChange={(timingMode) => setDraft((d) => ({ ...d, timingMode }))}
                onCustomChange={(customTime) => setDraft((d) => ({ ...d, customTime }))}
              />
              <label className={labelClass}>
                <span className={labelTextClass}>Notes (optional) — applies to every submitted row</span>
                <textarea
                  className={`${inputClass} min-h-16 py-2`}
                  value={draft.notes}
                  onChange={(e) => setDraft((d) => ({ ...d, notes: e.target.value }))}
                />
              </label>
            </div>
          </div>
        }
        rail={
          <section aria-label="Measurement summary" className={`${cardClass} flex flex-col gap-3`}>
            <h2 className="text-sm font-semibold text-wl-text">Record measurements</h2>
            <p className="text-sm text-wl-text-secondary">
              {filledCount === 0
                ? "No metric entered yet."
                : `${filledCount} metric(s) will be recorded as ${filledCount} independent command(s).`}
            </p>
            <StickyActionBar blockers={<BlockerList lines={[formError]} />}>
              <Button variant="primary" className="min-h-11 w-full" onClick={goToReview}>
                Review measurements
              </Button>
            </StickyActionBar>
          </section>
        }
      />
    </div>
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
  const { label: instrumentLabel } = useInstrumentLabels(farmId);
  const historyQuery = useMeasurementsForFarm(farmId, {
    metric: metric || undefined,
    reservoirId: reservoirId || undefined,
    windowStart: localInputToIso(windowStart) ?? undefined,
    windowEnd: localInputToIso(windowEnd) ?? undefined,
  });

  const samplingPointById = new Map((samplingPointsQuery.data ?? []).map((p) => [p.id, p]));
  const rows = [...(historyQuery.data ?? [])].sort(
    (a, b) => new Date(b.effective_at).getTime() - new Date(a.effective_at).getTime(),
  );
  const unitByMetric = new Map(METRICS.map((m) => [m.metric, m.label]));

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-end gap-3 rounded-xl border border-wl-border bg-wl-surface-raised p-3" role="toolbar" aria-label="History filters">
        <label className={`${labelClass} w-40`}>
          <span className={labelTextClass}>Metric</span>
          <select className={inputClass} value={metric} onChange={(e) => setMetric(e.target.value)}>
            {HISTORY_METRIC_OPTIONS.map((m) => (
              <option key={m || "all"} value={m}>
                {m ? unitByMetric.get(m) : "All metrics"}
              </option>
            ))}
          </select>
        </label>
        <label className={`${labelClass} w-56`}>
          <span className={labelTextClass}>Reservoir / Tank</span>
          <select className={inputClass} value={reservoirId} onChange={(e) => setReservoirId(e.target.value)}>
            <option value="">All reservoirs and points</option>
            {(reservoirsQuery.data ?? []).map((r) => (
              <option key={r.id} value={r.id}>{entityLabel(r)}</option>
            ))}
          </select>
        </label>
        <label className={`${labelClass} w-52`}>
          <span className={labelTextClass}>From</span>
          <input type="datetime-local" className={inputClass} value={windowStart} onChange={(e) => setWindowStart(e.target.value)} />
        </label>
        <label className={`${labelClass} w-52`}>
          <span className={labelTextClass}>To</span>
          <input type="datetime-local" className={inputClass} value={windowEnd} onChange={(e) => setWindowEnd(e.target.value)} />
        </label>
      </div>

      {historyQuery.isLoading && !historyQuery.data ? (
        <LoadingSkeleton rows={6} label="Loading measurement history" />
      ) : historyQuery.isError && !historyQuery.data ? (
        <ErrorState error={historyQuery.error} onRetry={() => historyQuery.refetch()} />
      ) : rows.length === 0 ? (
        <EmptyState title="No measurements match these filters" />
      ) : (
        <BoundedDataRegion
          label="Measurement history"
          footer={
            <span className="text-xs text-wl-text-secondary">
              {rows.length} measurement(s), newest first
              {historyQuery.isError ? " · could not refresh — showing previously loaded data" : ""}
            </span>
          }
        >
          <table className="w-full min-w-[44rem] text-sm">
            <thead className="sticky top-0 bg-wl-surface-raised">
              <tr className="text-left text-xs text-wl-text-secondary">
                <th className="px-3 py-2 font-medium">Sampling Point</th>
                <th className="px-3 py-2 font-medium">Measurement</th>
                <th className="px-3 py-2 font-medium">Effective</th>
                <th className="px-3 py-2 font-medium">Recorded</th>
                <th className="px-3 py-2 font-medium">Instrument</th>
                <th className="px-3 py-2 font-medium">Notes</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-wl-border">
              {rows.map((m) => {
                const point = samplingPointById.get(m.sampling_point_id);
                return (
                  <tr key={m.id}>
                    <td className="px-3 py-2">{entityLabel(point) ?? <span className="text-wl-text-tertiary">Sampling Point label unavailable</span>}</td>
                    <td className="px-3 py-2 tabular-nums">
                      <span className="font-medium">{unitByMetric.get(m.metric) ?? humanizeEnumCode(m.metric)}</span> {m.value} {m.unit}
                    </td>
                    <td className="px-3 py-2 text-xs">{formatDateTimeWithZoneLabel(m.effective_at)}</td>
                    <td className="px-3 py-2 text-xs">{formatDateTimeWithZoneLabel(m.recorded_at)}</td>
                    <td className="px-3 py-2 text-xs">{instrumentLabel(m.water_instrument_id) ?? "—"}</td>
                    <td className="px-3 py-2 text-xs">{m.notes ?? "—"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </BoundedDataRegion>
      )}
    </div>
  );
}

/** UX-OPS-001D: URL-backed Record / History views -- never the full History
 * stacked under the worksheet. */
export default function WaterMeasurementsPage() {
  const { farmId } = useParams<{ farmId: string }>();
  const { data: farm } = useFarm(farmId);
  const { view, setView } = useViewState<View>({ views: VIEWS, defaultView: "record" });
  const [locked, setLocked] = useState(false);

  return (
    <div>
      <WaterWorkspaceHeader
        farmId={farmId}
        title="Measurements"
        description={farm ? `pH, EC, solution temperature, and dissolved oxygen for ${farm.name}` : undefined}
        locked={locked}
      />
      <div className="mb-3">
        <ViewTabs
          items={[
            { value: "record", label: "Record" },
            { value: "history", label: "History" },
          ]}
          active={view}
          onChange={setView}
          disabled={locked}
        />
      </div>
      {/* Record stays mounted (hidden) while History is shown, so an
          unresolved run or partial receipt is never unmounted by a view change. */}
      <div hidden={view !== "record"}>
        <MeasurementRecorder farmId={farmId} onLockedChange={setLocked} />
      </div>
      {view === "history" && <MeasurementHistory farmId={farmId} />}
    </div>
  );
}
