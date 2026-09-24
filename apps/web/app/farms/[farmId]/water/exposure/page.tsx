"use client";

import { useParams } from "next/navigation";
import { useMemo, useState } from "react";

import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { LoadingSkeleton } from "@/components/LoadingSkeleton";
import { StatusBadge } from "@/components/StatusBadge";
import { BoundedDataRegion } from "@/components/layout/BoundedDataRegion";
import { InspectorEmptyState, InspectorShell } from "@/components/layout/InspectorShell";
import { SplitWorkspace } from "@/components/layout/SplitWorkspace";
import { ViewTabs } from "@/components/layout/ViewTabs";
import { Button } from "@/components/ui/Button";
import {
  Fact,
  FactList,
  WaterWorkspaceHeader,
  entityLabel,
  inputClass,
  labelClass,
  labelTextClass,
  localInputToIso,
} from "@/components/water/waterUi";
import type {
  LocationTreeNode,
  WaterExposureGapRead,
  WaterExposureIntervalRead,
} from "@/lib/api/client";
import { formatDateTime, formatDateTimeWithZoneLabel } from "@/lib/format/datetime";
import { humanizeEnumCode } from "@/lib/format/humanize";
import { useViewState } from "@/lib/navigation/useViewState";
import {
  useBatchWaterExposureTimeline,
  useCarriers,
  useCircuitWaterExposureTimeline,
  useFarm,
  useIrrigationCircuits,
  useLocationsTree,
  useOperationalSummary,
  useReservoirWaterExposureTimeline,
  useReservoirs,
  useWaterDeliveryPoints,
} from "@/lib/query/hooks";

/** PILOT-WATER-001B frozen evidence wording: exposure is traceability
 * evidence, never a health/disease claim. */
export function exposureKindLabel(kind: string): string {
  if (kind === "RECORDED_DELIVERY_EXPOSURE") return "Recorded Delivery Exposure";
  if (kind === "CONFIGURED_TOPOLOGY_EXPOSURE") return "Configured Topology Exposure";
  return kind;
}

const OPEN_SOURCE_LABELS: Record<string, string> = {
  BATCH_CARRIER_ASSIGNMENT: "Batch–Carrier assignment",
  OCCUPANCY: "Carrier occupancy",
  RESERVOIR_CIRCUIT_LINK: "Reservoir → Circuit link",
  CIRCUIT_DELIVERY_POINT_LINK: "Circuit → Delivery Point link",
  WATER_DELIVERY_EVENT: "Ongoing water delivery",
};

export function openSourceLabel(source: string): string {
  return OPEN_SOURCE_LABELS[source] ?? humanizeEnumCode(source);
}

export function gapReasonLabel(reason: string): string {
  return reason === "NO_COMPLETE_TOPOLOGY_ROUTE" ? "No complete topology route" : humanizeEnumCode(reason);
}

export function intervalConventionLabel(convention: string): string {
  return convention === "HALF_OPEN_START_INCLUSIVE_END_EXCLUSIVE"
    ? "Each row's start time is included and its end time is excluded, so touching rows do not overlap."
    : `Interval convention: ${convention}`;
}

/** Validates an explicit, timezone-aware window before any query. */
export function validateWindow(startLocal: string, endLocal: string): { start: string; end: string } | { error: string } | null {
  if (!startLocal || !endLocal) return null;
  const start = localInputToIso(startLocal);
  const end = localInputToIso(endLocal);
  if (!start || !end) return { error: "Enter a valid window start and end." };
  if (new Date(start).getTime() >= new Date(end).getTime()) return { error: "The window start must be before the window end." };
  return { start, end };
}

const VIEWS = ["batch", "reservoir", "circuit"] as const;
type View = (typeof VIEWS)[number];

function flattenLocations(nodes: LocationTreeNode[], prefix: string, into: Map<string, string>) {
  for (const node of nodes) {
    const path = prefix ? `${prefix} / ${node.code}` : node.code;
    into.set(node.id, path);
    flattenLocations(node.children ?? [], path, into);
  }
}

function useExposureLabels(farmId: string) {
  const batches = useOperationalSummary(farmId, "all");
  const carriers = useCarriers(farmId);
  const locations = useLocationsTree(farmId);
  const reservoirs = useReservoirs(farmId);
  const circuits = useIrrigationCircuits(farmId);
  const deliveryPoints = useWaterDeliveryPoints(farmId);
  return useMemo(() => {
    const locationPaths = new Map<string, string>();
    flattenLocations(locations.data ?? [], "", locationPaths);
    const code = <T extends { id: string; code: string }>(rows: T[] | undefined) => new Map((rows ?? []).map((r) => [r.id, r.code]));
    const named = <T extends { id: string; code: string; name: string }>(rows: T[] | undefined) =>
      new Map((rows ?? []).map((r) => [r.id, entityLabel(r) as string]));
    const batchCodes = code(batches.data);
    const carrierCodes = code(carriers.data);
    const reservoirLabels = named(reservoirs.data);
    const circuitLabels = named(circuits.data);
    const deliveryPointLabels = named(deliveryPoints.data);
    const reservoirCodes = code(reservoirs.data);
    const circuitCodes = code(circuits.data);
    const deliveryPointCodes = code(deliveryPoints.data);
    return {
      /** Compact route (codes) for dense rows; full names in the detail. */
      routeCodes: (r: { reservoir_id: string; irrigation_circuit_id: string; water_delivery_point_id: string }) =>
        [
          reservoirCodes.get(r.reservoir_id) ?? "Reservoir unavailable",
          circuitCodes.get(r.irrigation_circuit_id) ?? "Circuit unavailable",
          deliveryPointCodes.get(r.water_delivery_point_id) ?? "Delivery Point unavailable",
        ].join(" → "),
      batch: (id: string) => batchCodes.get(id) ?? "Batch label unavailable",
      carrier: (id: string) => carrierCodes.get(id) ?? "Carrier label unavailable",
      location: (id: string) => locationPaths.get(id) ?? "Location label unavailable",
      reservoir: (id: string) => reservoirLabels.get(id) ?? "Reservoir label unavailable",
      circuit: (id: string) => circuitLabels.get(id) ?? "Circuit label unavailable",
      deliveryPoint: (id: string) => deliveryPointLabels.get(id) ?? "Delivery Point label unavailable",
      batchOptions: batches.data ?? [],
      reservoirOptions: reservoirs.data ?? [],
      circuitOptions: circuits.data ?? [],
    };
  }, [batches.data, carriers.data, locations.data, reservoirs.data, circuits.data, deliveryPoints.data]);
}

type Labels = ReturnType<typeof useExposureLabels>;

function ClippingText({ row }: { row: { start_clipped_to_window: boolean; end_clipped_to_window: boolean; open_ended_sources: string[] } }) {
  const parts: string[] = [];
  if (row.start_clipped_to_window) parts.push("starts at window start");
  if (row.end_clipped_to_window) {
    parts.push(
      row.open_ended_sources.length > 0
        ? `clipped at window end (still open: ${row.open_ended_sources.map(openSourceLabel).join(", ")})`
        : "ends at window end",
    );
  }
  return <span>{parts.length > 0 ? parts.join("; ") : "Not clipped"}</span>;
}

function WindowSummary({
  windowStart, windowEnd, convention, openSources,
}: {
  windowStart: string; windowEnd: string; convention: string; openSources: string[];
}) {
  return (
    <div className="flex flex-col gap-1 rounded-lg border border-wl-border bg-wl-surface-raised px-3 py-2 text-xs text-wl-text-secondary" data-testid="window-summary">
      <p>
        <span className="font-medium text-wl-text">Returned window:</span> {formatDateTimeWithZoneLabel(windowStart)} (included) –{" "}
        {formatDateTimeWithZoneLabel(windowEnd)} (excluded). {intervalConventionLabel(convention)}
      </p>
      {openSources.length > 0 && (
        <p role="note" className="text-wl-hold-fg">
          Some rows are clipped at the selected window end because these sources are still open:{" "}
          {openSources.map(openSourceLabel).join(", ")}. The window end is not a recorded end.
        </p>
      )}
    </div>
  );
}

type Selection = { kind: "interval"; index: number } | { kind: "gap"; index: number } | null;

function IntervalTable({
  intervals, labels, selection, onSelect,
}: {
  intervals: WaterExposureIntervalRead[]; labels: Labels; selection: Selection; onSelect: (s: Selection) => void;
}) {
  return (
    <BoundedDataRegion
      label="Exposure intervals"
      footer={<span className="text-xs text-wl-text-secondary">{intervals.length} interval row(s) — one per returned interval, never merged</span>}
    >
      <table className="w-full min-w-[40rem] text-sm [&_td]:align-top">
        <thead className="sticky top-0 bg-wl-surface-raised">
          <tr className="text-left text-xs text-wl-text-secondary">
            <th className="px-3 py-2 font-medium">Interval — start included, end excluded (your local time)</th>
            <th className="px-3 py-2 font-medium">Evidence</th>
            <th className="px-3 py-2 font-medium">Reservoir → Circuit → Delivery Point</th>
            <th className="px-3 py-2 font-medium">Batch · Carrier · Location</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-wl-border">
          {intervals.map((row, index) => {
            const isSelected = selection?.kind === "interval" && selection.index === index;
            return (
              <tr key={index} data-testid="exposure-interval-row" className={isSelected ? "bg-wl-brand-subtle" : undefined}>
                <td className="px-3 py-2 text-xs">
                  <button
                    type="button"
                    className="min-h-11 text-left font-medium text-wl-text underline-offset-2 hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-wl-focus"
                    aria-pressed={isSelected}
                    onClick={() => onSelect({ kind: "interval", index })}
                  >
                    {formatDateTime(row.interval_start)} – {formatDateTime(row.interval_end)}
                  </button>
                  {(row.start_clipped_to_window || row.end_clipped_to_window) && (
                    <span className="block text-[11px] text-wl-hold-fg">
                      <ClippingText row={row} />
                    </span>
                  )}
                </td>
                <td className="px-3 py-2">
                  <StatusBadge
                    label={exposureKindLabel(row.exposure_kind)}
                    tone={row.exposure_kind === "RECORDED_DELIVERY_EXPOSURE" ? "active" : "neutral"}
                  />
                </td>
                <td className="px-3 py-2 text-xs">{labels.routeCodes(row)}</td>
                <td className="px-3 py-2 text-xs">
                  {labels.batch(row.batch_id)} · {labels.carrier(row.carrier_id)} · {labels.location(row.location_id)}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </BoundedDataRegion>
  );
}

function GapTable({
  gaps, labels, selection, onSelect,
}: {
  gaps: WaterExposureGapRead[]; labels: Labels; selection: Selection; onSelect: (s: Selection) => void;
}) {
  return (
    <section aria-label="Batch gaps" className="flex flex-col gap-1">
      <h3 className="text-sm font-semibold text-wl-text">Gaps ({gaps.length})</h3>
      <p className="text-xs text-wl-text-secondary">
        Placed time (valid assignment and occupancy) that no complete Reservoir → Circuit → Delivery Point route covers. A gap is not an exposure kind.
      </p>
      {gaps.length === 0 ? (
        <p className="text-xs text-wl-text-tertiary">No gaps returned in this window.</p>
      ) : (
        <ul className="divide-y divide-wl-border rounded-lg border border-wl-border">
          {gaps.map((gap, index) => {
            const isSelected = selection?.kind === "gap" && selection.index === index;
            return (
              <li key={index} data-testid="exposure-gap-row" className={`px-3 py-2 text-xs ${isSelected ? "bg-wl-brand-subtle" : ""}`}>
                <button
                  type="button"
                  aria-pressed={isSelected}
                  className="min-h-11 text-left focus-visible:outline focus-visible:outline-2 focus-visible:outline-wl-focus"
                  onClick={() => onSelect({ kind: "gap", index })}
                >
                  <span className="font-medium text-wl-text">{gapReasonLabel(gap.reason)}</span> ·{" "}
                  {formatDateTimeWithZoneLabel(gap.gap_start)} – {formatDateTimeWithZoneLabel(gap.gap_end)} ·{" "}
                  {labels.carrier(gap.carrier_id)} · {labels.location(gap.location_id)} · <ClippingText row={gap} />
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

function ProvenanceDetail({
  selection, intervals, gaps, labels, onClose,
}: {
  selection: Selection; intervals: WaterExposureIntervalRead[]; gaps: WaterExposureGapRead[]; labels: Labels; onClose: () => void;
}) {
  if (selection?.kind === "interval" && intervals[selection.index]) {
    const row = intervals[selection.index];
    return (
      <InspectorShell title={exposureKindLabel(row.exposure_kind)} subtitle="Source provenance for this one interval" onClose={onClose}>
        <FactList>
          <Fact label="Start (included)">{formatDateTimeWithZoneLabel(row.interval_start)}</Fact>
          <Fact label="End (excluded)">{formatDateTimeWithZoneLabel(row.interval_end)}</Fact>
          <Fact label="Route">{labels.reservoir(row.reservoir_id)} → {labels.circuit(row.irrigation_circuit_id)} → {labels.deliveryPoint(row.water_delivery_point_id)}</Fact>
          <Fact label="Placement">{labels.batch(row.batch_id)} · {labels.carrier(row.carrier_id)} · {labels.location(row.location_id)}</Fact>
          <Fact label="Clipping"><ClippingText row={row} /></Fact>
        </FactList>
        <dl className="grid grid-cols-1 gap-1 break-all font-mono text-[11px] text-wl-text-secondary">
          {([
            ["Batch", row.batch_id], ["Carrier", row.carrier_id], ["Location", row.location_id],
            ["Reservoir", row.reservoir_id], ["Irrigation Circuit", row.irrigation_circuit_id],
            ["Delivery Point", row.water_delivery_point_id], ["Delivery Point Location", row.delivery_point_location_id],
            ["Water Delivery Event", row.water_delivery_event_id ?? "none (topology only)"],
            ["Batch Carrier Assignment", row.batch_carrier_assignment_id], ["Occupancy", row.occupancy_id],
            ["Reservoir → Circuit link", row.reservoir_circuit_link_id], ["Circuit → Delivery Point link", row.circuit_delivery_point_link_id],
          ] as const).map(([k, v]) => (
            <div key={k}><dt className="inline font-sans font-medium">{k}: </dt><dd className="inline">{v}</dd></div>
          ))}
        </dl>
      </InspectorShell>
    );
  }
  if (selection?.kind === "gap" && gaps[selection.index]) {
    const gap = gaps[selection.index];
    return (
      <InspectorShell title={gapReasonLabel(gap.reason)} subtitle="Gap provenance" onClose={onClose}>
        <FactList>
          <Fact label="Start (included)">{formatDateTimeWithZoneLabel(gap.gap_start)}</Fact>
          <Fact label="End (excluded)">{formatDateTimeWithZoneLabel(gap.gap_end)}</Fact>
          <Fact label="Placement">{labels.batch(gap.batch_id)} · {labels.carrier(gap.carrier_id)} · {labels.location(gap.location_id)}</Fact>
          <Fact label="Clipping"><ClippingText row={gap} /></Fact>
        </FactList>
        <dl className="grid grid-cols-1 gap-1 break-all font-mono text-[11px] text-wl-text-secondary">
          {([
            ["Batch", gap.batch_id], ["Carrier", gap.carrier_id], ["Location", gap.location_id],
            ["Batch Carrier Assignment", gap.batch_carrier_assignment_id], ["Occupancy", gap.occupancy_id],
          ] as const).map(([k, v]) => (
            <div key={k}><dt className="inline font-sans font-medium">{k}: </dt><dd className="inline">{v}</dd></div>
          ))}
        </dl>
      </InspectorShell>
    );
  }
  return <InspectorEmptyState label="Select an interval or gap to see its full source provenance." />;
}

function ExposureView({ farmId, view }: { farmId: string; view: View }) {
  const labels = useExposureLabels(farmId);
  const [entityId, setEntityId] = useState("");
  const [startLocal, setStartLocal] = useState("");
  const [endLocal, setEndLocal] = useState("");
  const [applied, setApplied] = useState<{ entityId: string; start: string; end: string } | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [selection, setSelection] = useState<Selection>(null);

  const batchQuery = useBatchWaterExposureTimeline(farmId, view === "batch" ? applied?.entityId : undefined, applied?.start, applied?.end);
  const reservoirQuery = useReservoirWaterExposureTimeline(farmId, view === "reservoir" ? applied?.entityId : undefined, applied?.start, applied?.end);
  const circuitQuery = useCircuitWaterExposureTimeline(farmId, view === "circuit" ? applied?.entityId : undefined, applied?.start, applied?.end);
  const query = view === "batch" ? batchQuery : view === "reservoir" ? reservoirQuery : circuitQuery;

  function show() {
    setFormError(null);
    if (!entityId) return setFormError(`Choose a ${view === "batch" ? "Batch" : view === "reservoir" ? "Reservoir / Tank" : "Irrigation Circuit"}.`);
    const window = validateWindow(startLocal, endLocal);
    if (!window) return setFormError("Enter both the window start and the window end.");
    if ("error" in window) return setFormError(window.error);
    setSelection(null);
    setApplied({ entityId, start: window.start, end: window.end });
  }

  const options =
    view === "batch"
      ? labels.batchOptions.map((b) => ({ id: b.id, label: b.code }))
      : view === "reservoir"
        ? labels.reservoirOptions.map((r) => ({ id: r.id, label: entityLabel(r) as string }))
        : labels.circuitOptions.map((c) => ({ id: c.id, label: entityLabel(c) as string }));
  const entityName = view === "batch" ? "Batch" : view === "reservoir" ? "Reservoir / Tank" : "Irrigation Circuit";

  const data = query.data;
  const intervals = data?.intervals ?? [];
  const gaps = data && "gaps" in data ? data.gaps : [];
  const openSources = [...new Set([...intervals, ...gaps].flatMap((r) => r.open_ended_sources))].sort();

  let result;
  if (!applied) result = <p className="text-sm text-wl-text-secondary">Choose a {entityName} and an explicit window, then Show exposure.</p>;
  else if (query.isLoading && !data) result = <LoadingSkeleton rows={6} label="Loading exposure timeline" />;
  else if (query.isError && !data) result = <ErrorState error={query.error} onRetry={() => query.refetch()} />;
  else if (data) {
    result = (
      <div className="flex flex-col gap-3">
        <WindowSummary windowStart={data.window_start} windowEnd={data.window_end} convention={data.interval_convention} openSources={openSources} />
        {intervals.length === 0 ? (
          <EmptyState
            title="No matching interval evidence in this window"
            description={
              view === "batch"
                ? "No interval was returned. Absence of rows is not proof of no water use: time outside a valid assignment and occupancy is not reported."
                : "No matching interval evidence was returned for this window. This is not a health or causation conclusion."
            }
          />
        ) : (
          <IntervalTable intervals={intervals} labels={labels} selection={selection} onSelect={setSelection} />
        )}
        {view === "batch" ? (
          <>
            <GapTable gaps={gaps} labels={labels} selection={selection} onSelect={setSelection} />
            <p className="text-xs text-wl-text-tertiary">
              Time outside a valid Batch–Carrier assignment and occupancy is neither an interval nor a gap. A missing row is not proof of no water use.
            </p>
          </>
        ) : (
          <p className="text-xs text-wl-text-tertiary">
            This reverse view returns matched intervals only — it does not return Batch gap rows.
          </p>
        )}
        {query.isError && <p className="text-xs text-wl-text-tertiary">Could not refresh — showing previously loaded data.</p>}
      </div>
    );
  }

  return (
    <SplitWorkspace
      main={
        <div className="flex min-w-0 flex-col gap-3">
          <div role="toolbar" aria-label="Exposure query" className="flex flex-wrap items-end gap-3 rounded-xl border border-wl-border bg-wl-surface-raised p-3">
            <label className={`${labelClass} w-56`}>
              <span className={labelTextClass}>{entityName}</span>
              <select className={inputClass} value={entityId} onChange={(e) => setEntityId(e.target.value)}>
                <option value="">Select…</option>
                {options.map((o) => <option key={o.id} value={o.id}>{o.label}</option>)}
              </select>
            </label>
            <label className={`${labelClass} w-52`}>
              <span className={labelTextClass}>Window start (included)</span>
              <input type="datetime-local" className={inputClass} value={startLocal} onChange={(e) => setStartLocal(e.target.value)} />
            </label>
            <label className={`${labelClass} w-52`}>
              <span className={labelTextClass}>Window end (excluded)</span>
              <input type="datetime-local" className={inputClass} value={endLocal} onChange={(e) => setEndLocal(e.target.value)} />
            </label>
            <Button variant="primary" className="min-h-11" onClick={show}>Show exposure</Button>
          </div>
          {formError && <p role="alert" className="text-xs font-medium text-wl-flag-fg">{formError}</p>}
          {result}
        </div>
      }
      rail={<ProvenanceDetail selection={selection} intervals={intervals} gaps={gaps} labels={labels} onClose={() => setSelection(null)} />}
    />
  );
}

/** UX-OPS-001D: Water Exposure on the exact UX-OPS-001D0 interval timelines
 * -- one row per returned interval (never merged/deduplicated), explicit
 * half-open semantics, Batch gaps, and open-source clipping. Evidence only;
 * never a disease, contamination, or causation claim. */
export default function WaterExposurePage() {
  const { farmId } = useParams<{ farmId: string }>();
  const { data: farm } = useFarm(farmId);
  const { view, setView } = useViewState<View>({ views: VIEWS, defaultView: "batch" });

  return (
    <div>
      <WaterWorkspaceHeader
        farmId={farmId}
        title="Exposure"
        description={
          farm
            ? `Water exposure evidence for ${farm.name} — from configured topology, placement, and recorded deliveries. Evidence only, never a health claim.`
            : undefined
        }
      />
      <div className="mb-3">
        <ViewTabs
          items={[
            { value: "batch", label: "By Batch" },
            { value: "reservoir", label: "By Reservoir" },
            { value: "circuit", label: "By Circuit" },
          ]}
          active={view}
          onChange={setView}
        />
      </div>
      <ExposureView key={view} farmId={farmId} view={view} />
    </div>
  );
}
