"use client";

import { useParams } from "next/navigation";
import { useState } from "react";

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
import type { ReservoirEventCreate, WaterDeliveryEventCreate } from "@/lib/api/client";
import { AppError } from "@/lib/errors/adapter";
import { formatDateTimeWithZoneLabel } from "@/lib/format/datetime";
import { humanizeEnumCode } from "@/lib/format/humanize";
import {
  useDeliveryEventsForFarm,
  useFarm,
  useInventoryItems,
  useIrrigationCircuits,
  useMixesForReservoir,
  useRecordDeliveryEvent,
  useRecordReservoirEvent,
  useReservoirEventsForFarm,
  useReservoirs,
  useUoms,
} from "@/lib/query/hooks";

function errorMessage(error: unknown): string {
  return error instanceof AppError ? error.message : "Something went wrong. Please try again.";
}

const inputClass =
  "min-h-10 w-full rounded-md border border-wl-border bg-wl-surface-raised px-3 text-sm text-wl-text focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-wl-focus";
const labelClass = "flex flex-col gap-1 text-sm";
const labelTextClass = "text-xs font-medium uppercase tracking-wide text-wl-text-secondary";

const RESERVOIR_EVENT_TYPES = [
  "NUTRIENT_ADDITION", "WATER_TOP_UP", "PH_ADJUSTMENT", "SOLUTION_REPLACEMENT", "FLUSH", "DRAIN", "OTHER",
];

/** PILOT-WATER-001B: fast Reservoir/Tank event entry -- never calculates or
 * infers the resulting EC/pH; that is what Measurements are for. */
function ReservoirEventForm({ farmId }: { farmId: string }) {
  const reservoirsQuery = useReservoirs(farmId);
  const uomsQuery = useUoms();
  const inventoryItemsQuery = useInventoryItems({ status: "active" });

  const [reservoirId, setReservoirId] = useState("");
  const [eventType, setEventType] = useState("");
  const [quantity, setQuantity] = useState("");
  const [uomId, setUomId] = useState("");
  const [inventoryItemId, setInventoryItemId] = useState("");
  const [notes, setNotes] = useState("");
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [savedAt, setSavedAt] = useState<number | null>(null);

  const recordEvent = useRecordReservoirEvent(farmId, reservoirId);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitError(null);
    if (!reservoirId || !eventType) {
      setSubmitError("Choose a Reservoir/Tank and an event type.");
      return;
    }
    const payload: ReservoirEventCreate = {
      event_type: eventType,
      quantity: quantity.trim() || null,
      quantity_uom_id: quantity.trim() ? uomId || null : null,
      inventory_item_id: inventoryItemId || null,
      notes: notes.trim() || null,
      client_command_id: crypto.randomUUID(),
    };
    try {
      await recordEvent.mutateAsync(payload);
      setQuantity("");
      setInventoryItemId("");
      setNotes("");
      setSavedAt(Date.now());
    } catch (err) {
      setSubmitError(errorMessage(err));
    }
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-3 rounded-xl border border-wl-border bg-wl-surface-raised p-4">
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
        <label className={labelClass}>
          <span className={labelTextClass}>Reservoir / Tank</span>
          <select className={inputClass} value={reservoirId} onChange={(e) => setReservoirId(e.target.value)} required>
            <option value="">Select a Reservoir…</option>
            {(reservoirsQuery.data ?? []).map((r) => (
              <option key={r.id} value={r.id}>{r.code} — {r.name}</option>
            ))}
          </select>
        </label>
        <label className={labelClass}>
          <span className={labelTextClass}>Event Type</span>
          <select className={inputClass} value={eventType} onChange={(e) => setEventType(e.target.value)} required>
            <option value="">Select an event…</option>
            {RESERVOIR_EVENT_TYPES.map((t) => (
              <option key={t} value={t}>{humanizeEnumCode(t)}</option>
            ))}
          </select>
        </label>
      </div>
      <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
        <label className={labelClass}>
          <span className={labelTextClass}>Quantity (optional)</span>
          <input className={inputClass} value={quantity} onChange={(e) => setQuantity(e.target.value)} />
        </label>
        <label className={labelClass}>
          <span className={labelTextClass}>Unit</span>
          <select className={inputClass} value={uomId} onChange={(e) => setUomId(e.target.value)}>
            <option value="">Select unit…</option>
            {(uomsQuery.data ?? []).map((u) => (
              <option key={u.id} value={u.id}>{u.code}</option>
            ))}
          </select>
        </label>
        <label className={labelClass}>
          <span className={labelTextClass}>Inventory Item (optional)</span>
          <select className={inputClass} value={inventoryItemId} onChange={(e) => setInventoryItemId(e.target.value)}>
            <option value="">Not linked to Store</option>
            {(inventoryItemsQuery.data ?? []).map((item) => (
              <option key={item.id} value={item.id}>{item.name}</option>
            ))}
          </select>
        </label>
      </div>
      <label className={labelClass}>
        <span className={labelTextClass}>Notes</span>
        <textarea className={`${inputClass} min-h-16`} value={notes} onChange={(e) => setNotes(e.target.value)} />
      </label>
      {submitError && <p className="text-xs text-wl-flag-fg">{submitError}</p>}
      {savedAt && !submitError && <p className="text-xs text-wl-grow-fg">Event recorded.</p>}
      <Button type="submit" disabled={recordEvent.isPending}>
        {recordEvent.isPending ? "Recording…" : "Record Event"}
      </Button>
    </form>
  );
}

function RecentReservoirEvents({ farmId }: { farmId: string }) {
  const eventsQuery = useReservoirEventsForFarm(farmId);
  const reservoirsQuery = useReservoirs(farmId);
  const reservoirById = new Map((reservoirsQuery.data ?? []).map((r) => [r.id, r]));
  const rows = [...(eventsQuery.data ?? [])].sort((a, b) => new Date(b.effective_at).getTime() - new Date(a.effective_at).getTime()).slice(0, 20);

  if (eventsQuery.isLoading && !eventsQuery.data) return <LoadingSkeleton rows={3} label="Loading Reservoir events" />;
  if (eventsQuery.isError && !eventsQuery.data) return <ErrorState error={eventsQuery.error} onRetry={() => eventsQuery.refetch()} />;
  if (rows.length === 0) return <EmptyState title="No Reservoir events recorded yet" />;

  return (
    <div className={tableWrapperClass}>
      <table className="w-full text-sm">
        <thead>
          <tr className={tableHeadRowClass}>
            <th className={tableThClass}>Reservoir / Tank</th>
            <th className={tableThClass}>Event</th>
            <th className={`${tableThClass} text-right`}>Quantity</th>
            <th className={tableThClass}>Effective</th>
          </tr>
        </thead>
        <tbody className={tableBodyDividerClass}>
          {rows.map((ev) => {
            const reservoir = reservoirById.get(ev.reservoir_id);
            return (
              <tr key={ev.id} className={tableRowHoverClass}>
                <td className={tableTdClass}>{reservoir ? `${reservoir.code} — ${reservoir.name}` : ev.reservoir_id.slice(0, 8)}</td>
                <td className={tableTdClass}>{humanizeEnumCode(ev.event_type)}</td>
                <td className={`${tableTdClass} text-right tabular-nums`}>{ev.quantity ?? "—"}</td>
                <td className={tableTdClass}>{formatDateTimeWithZoneLabel(ev.effective_at)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/** PILOT-WATER-001B: Delivery/Irrigation -- start/end time, delivered volume
 * only when measured (blank stays blank, never defaults to 0), an optional
 * related Mix (never inferred), and supports an open-ended continuous
 * delivery by simply leaving `effective_end` unset. */
function DeliveryForm({ farmId }: { farmId: string }) {
  const reservoirsQuery = useReservoirs(farmId);
  const circuitsQuery = useIrrigationCircuits(farmId);
  const uomsQuery = useUoms();

  const [reservoirId, setReservoirId] = useState("");
  const [circuitId, setCircuitId] = useState("");
  const [effectiveStart, setEffectiveStart] = useState("");
  const [effectiveEnd, setEffectiveEnd] = useState("");
  const [ongoing, setOngoing] = useState(true);
  const [deliveredVolume, setDeliveredVolume] = useState("");
  const [volumeUomId, setVolumeUomId] = useState("");
  const [mixId, setMixId] = useState("");
  const [notes, setNotes] = useState("");
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [savedAt, setSavedAt] = useState<number | null>(null);

  const mixesQuery = useMixesForReservoir(reservoirId || undefined);
  const recordDelivery = useRecordDeliveryEvent(farmId);
  const volumeUoms = (uomsQuery.data ?? []).filter((u) => u.quantity_kind === "volume");

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitError(null);
    if (!reservoirId || !circuitId) {
      setSubmitError("Choose a source Reservoir and a Circuit.");
      return;
    }
    const payload: WaterDeliveryEventCreate = {
      reservoir_id: reservoirId,
      irrigation_circuit_id: circuitId,
      effective_start: effectiveStart ? new Date(effectiveStart).toISOString() : null,
      effective_end: ongoing ? null : effectiveEnd ? new Date(effectiveEnd).toISOString() : null,
      delivered_volume: deliveredVolume.trim() || null,
      delivered_volume_uom_id: deliveredVolume.trim() ? volumeUomId || null : null,
      nutrient_mix_id: mixId || null,
      notes: notes.trim() || null,
      client_command_id: crypto.randomUUID(),
    };
    try {
      await recordDelivery.mutateAsync(payload);
      setDeliveredVolume("");
      setMixId("");
      setNotes("");
      setSavedAt(Date.now());
    } catch (err) {
      setSubmitError(errorMessage(err));
    }
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-3 rounded-xl border border-wl-border bg-wl-surface-raised p-4">
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
        <label className={labelClass}>
          <span className={labelTextClass}>Source Reservoir</span>
          <select className={inputClass} value={reservoirId} onChange={(e) => { setReservoirId(e.target.value); setMixId(""); }} required>
            <option value="">Select a Reservoir…</option>
            {(reservoirsQuery.data ?? []).map((r) => (
              <option key={r.id} value={r.id}>{r.code} — {r.name}</option>
            ))}
          </select>
        </label>
        <label className={labelClass}>
          <span className={labelTextClass}>Irrigation Circuit</span>
          <select className={inputClass} value={circuitId} onChange={(e) => setCircuitId(e.target.value)} required>
            <option value="">Select a Circuit…</option>
            {(circuitsQuery.data ?? []).map((c) => (
              <option key={c.id} value={c.id}>{c.code} — {c.name}</option>
            ))}
          </select>
        </label>
      </div>

      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
        <label className={labelClass}>
          <span className={labelTextClass}>Start Time (blank = now)</span>
          <input type="datetime-local" className={inputClass} value={effectiveStart} onChange={(e) => setEffectiveStart(e.target.value)} />
        </label>
        <div className="flex flex-col gap-1">
          <span className={labelTextClass}>End Time</span>
          <label className="flex items-center gap-2 text-sm text-wl-text">
            <input type="checkbox" checked={ongoing} onChange={(e) => setOngoing(e.target.checked)} />
            Ongoing / continuous (e.g. DWC) — no end time yet
          </label>
          {!ongoing && (
            <input type="datetime-local" className={inputClass} value={effectiveEnd} onChange={(e) => setEffectiveEnd(e.target.value)} />
          )}
        </div>
      </div>

      <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
        <label className={labelClass}>
          <span className={labelTextClass}>Delivered Volume (only if measured)</span>
          <input className={inputClass} value={deliveredVolume} onChange={(e) => setDeliveredVolume(e.target.value)} placeholder="Not measured" />
        </label>
        <label className={labelClass}>
          <span className={labelTextClass}>Volume Unit</span>
          <select className={inputClass} value={volumeUomId} onChange={(e) => setVolumeUomId(e.target.value)}>
            <option value="">Select unit…</option>
            {volumeUoms.map((u) => (
              <option key={u.id} value={u.id}>{u.code}</option>
            ))}
          </select>
        </label>
        <label className={labelClass}>
          <span className={labelTextClass}>Related Mix (optional)</span>
          <select className={inputClass} value={mixId} onChange={(e) => setMixId(e.target.value)} disabled={!reservoirId}>
            <option value="">No related Mix</option>
            {(mixesQuery.data ?? []).map((m) => (
              <option key={m.id} value={m.id}>{formatDateTimeWithZoneLabel(m.effective_at)}</option>
            ))}
          </select>
        </label>
      </div>

      <label className={labelClass}>
        <span className={labelTextClass}>Notes</span>
        <textarea className={`${inputClass} min-h-16`} value={notes} onChange={(e) => setNotes(e.target.value)} />
      </label>

      {submitError && <p className="text-xs text-wl-flag-fg">{submitError}</p>}
      {savedAt && !submitError && <p className="text-xs text-wl-grow-fg">Delivery recorded.</p>}

      <Button type="submit" disabled={recordDelivery.isPending}>
        {recordDelivery.isPending ? "Recording…" : "Record Delivery"}
      </Button>
    </form>
  );
}

function RecentDeliveries({ farmId }: { farmId: string }) {
  const deliveriesQuery = useDeliveryEventsForFarm(farmId);
  const reservoirsQuery = useReservoirs(farmId);
  const circuitsQuery = useIrrigationCircuits(farmId);
  const reservoirById = new Map((reservoirsQuery.data ?? []).map((r) => [r.id, r]));
  const circuitById = new Map((circuitsQuery.data ?? []).map((c) => [c.id, c]));
  const rows = [...(deliveriesQuery.data ?? [])].sort((a, b) => new Date(b.effective_start).getTime() - new Date(a.effective_start).getTime()).slice(0, 20);

  if (deliveriesQuery.isLoading && !deliveriesQuery.data) return <LoadingSkeleton rows={3} label="Loading deliveries" />;
  if (deliveriesQuery.isError && !deliveriesQuery.data) return <ErrorState error={deliveriesQuery.error} onRetry={() => deliveriesQuery.refetch()} />;
  if (rows.length === 0) return <EmptyState title="No deliveries recorded yet" />;

  return (
    <div className={tableWrapperClass}>
      <table className="w-full text-sm">
        <thead>
          <tr className={tableHeadRowClass}>
            <th className={tableThClass}>Reservoir → Circuit</th>
            <th className={tableThClass}>Window</th>
            <th className={`${tableThClass} text-right`}>Delivered Volume</th>
          </tr>
        </thead>
        <tbody className={tableBodyDividerClass}>
          {rows.map((d) => {
            const reservoir = reservoirById.get(d.reservoir_id);
            const circuit = circuitById.get(d.irrigation_circuit_id);
            return (
              <tr key={d.id} className={tableRowHoverClass}>
                <td className={tableTdClass}>
                  {(reservoir ? reservoir.code : d.reservoir_id.slice(0, 8))} → {(circuit ? circuit.code : d.irrigation_circuit_id.slice(0, 8))}
                </td>
                <td className={tableTdClass}>
                  {formatDateTimeWithZoneLabel(d.effective_start)} – {d.effective_end ? formatDateTimeWithZoneLabel(d.effective_end) : "ongoing"}
                </td>
                <td className={`${tableTdClass} text-right tabular-nums`}>{d.delivered_volume ?? "Not measured"}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export default function WaterDeliveryPage() {
  const { farmId } = useParams<{ farmId: string }>();
  const { data: farm } = useFarm(farmId);

  return (
    <div>
      <PageHeader
        title="Delivery"
        description={farm ? `Reservoir events and irrigation deliveries for ${farm.name}` : "Reservoir events and irrigation deliveries"}
        breadcrumbs={
          <Breadcrumbs items={[
            { label: "Home", href: `/farms/${farmId}` },
            { label: "Water & Nutrients", href: `/farms/${farmId}/water` },
            { label: "Delivery" },
          ]}
          />
        }
      />
      <WaterSubNav farmId={farmId} />

      <section className="flex flex-col gap-2">
        <h2 className="font-serif text-base font-semibold text-wl-text">Reservoir / Tank Event</h2>
        <ReservoirEventForm farmId={farmId} />
      </section>
      <section className="mt-4 flex flex-col gap-2">
        <h2 className="text-sm font-medium text-wl-text-secondary">Recent Reservoir Events</h2>
        <RecentReservoirEvents farmId={farmId} />
      </section>

      <section className="mt-6 flex flex-col gap-2">
        <h2 className="font-serif text-base font-semibold text-wl-text">Delivery / Irrigation</h2>
        <DeliveryForm farmId={farmId} />
      </section>
      <section className="mt-4 flex flex-col gap-2">
        <h2 className="text-sm font-medium text-wl-text-secondary">Recent Deliveries</h2>
        <RecentDeliveries farmId={farmId} />
      </section>
    </div>
  );
}
