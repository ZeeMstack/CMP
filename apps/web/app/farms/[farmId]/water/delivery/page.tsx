"use client";

import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { useState } from "react";

import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { LoadingSkeleton } from "@/components/LoadingSkeleton";
import { StatusBadge } from "@/components/StatusBadge";
import { BoundedDataRegion } from "@/components/layout/BoundedDataRegion";
import { InspectorEmptyState, InspectorShell } from "@/components/layout/InspectorShell";
import { QueueList, QueueRow } from "@/components/layout/QueueRow";
import { SplitWorkspace } from "@/components/layout/SplitWorkspace";
import { StickyActionBar } from "@/components/layout/StickyActionBar";
import { ViewTabs } from "@/components/layout/ViewTabs";
import { Button } from "@/components/ui/Button";
import {
  EndDeliveryFlow,
  EndDeliveryReceipt,
  type DeliveryContext,
  type EndFlowState,
  type FrozenEnd,
} from "@/components/water/EndDeliveryFlow";
import { NewDeliveryFlow, NewDeliveryReceipt, type FrozenDelivery } from "@/components/water/NewDeliveryFlow";
import {
  BlockerList,
  Fact,
  FactList,
  TimingField,
  WaterWorkspaceHeader,
  cardClass,
  commandErrorLine,
  entityLabel,
  inputClass,
  labelClass,
  labelTextClass,
  linkButtonClass,
  localInputToIso,
  nowAsLocalInput,
  type TimingMode,
} from "@/components/water/waterUi";
import type { ReservoirEventCreate, ReservoirEventRead, WaterDeliveryEventRead } from "@/lib/api/client";
import { settleFrozenAttempt, useFrozenSubmission, useReportCommandLocked } from "@/lib/commands/frozenSubmission";
import { AppError } from "@/lib/errors/adapter";
import { formatDateTime, formatDateTimeWithZoneLabel } from "@/lib/format/datetime";
import { humanizeEnumCode } from "@/lib/format/humanize";
import { useViewState } from "@/lib/navigation/useViewState";
import {
  useDeliveryEvent,
  useDeliveryEventsForFarm,
  useEndDeliveryEvent,
  useFarm,
  useInventoryItems,
  useIrrigationCircuits,
  useRecordDeliveryEvent,
  useRecordReservoirEvent,
  useReservoirCircuitLinks,
  useReservoirEventsForFarm,
  useReservoirs,
  useUoms,
} from "@/lib/query/hooks";

const VIEWS = ["deliveries", "reservoir-events"] as const;
type View = (typeof VIEWS)[number];

export const RESERVOIR_EVENT_TYPES = [
  "NUTRIENT_ADDITION", "WATER_TOP_UP", "PH_ADJUSTMENT", "SOLUTION_REPLACEMENT", "FLUSH", "DRAIN", "OTHER",
];

/** Ongoing first (newest start first), then ended (newest start first). */
export function orderDeliveries(rows: WaterDeliveryEventRead[]): WaterDeliveryEventRead[] {
  const byStart = (a: WaterDeliveryEventRead, b: WaterDeliveryEventRead) =>
    new Date(b.effective_start).getTime() - new Date(a.effective_start).getTime();
  return [...rows.filter((d) => d.effective_end === null).sort(byStart), ...rows.filter((d) => d.effective_end !== null).sort(byStart)];
}

function useRouteLabel(farmId: string) {
  const reservoirs = useReservoirs(farmId);
  const circuits = useIrrigationCircuits(farmId);
  return (d: { reservoir_id: string; irrigation_circuit_id: string }) => {
    const r = entityLabel((reservoirs.data ?? []).find((x) => x.id === d.reservoir_id)) ?? "Reservoir label unavailable";
    const c = entityLabel((circuits.data ?? []).find((x) => x.id === d.irrigation_circuit_id)) ?? "Circuit label unavailable";
    return `${r} → ${c}`;
  };
}

/** Irrigation deliveries mode. Both command attempts (New Delivery, End
 * Delivery) and the End flow's state live HERE, above the list selection
 * and the rail, so selecting another row, a refetch, or a row leaving the
 * list can never unmount or retarget an unresolved attempt. */
function DeliveriesMode({ farmId, onLockedChange }: { farmId: string; onLockedChange: (locked: boolean) => void }) {
  const searchParams = useSearchParams();
  const { selected, setSelected } = useViewState<View>({ views: VIEWS, defaultView: "deliveries" });
  const deliveriesQuery = useDeliveryEventsForFarm(farmId);
  const reservoirsQuery = useReservoirs(farmId);
  const circuitsQuery = useIrrigationCircuits(farmId);
  const linksQuery = useReservoirCircuitLinks(farmId);
  const uomsQuery = useUoms();
  const routeLabel = useRouteLabel(farmId);
  const recordDelivery = useRecordDeliveryEvent(farmId);
  const endDelivery = useEndDeliveryEvent(farmId);
  const detailQuery = useDeliveryEvent(farmId, selected ?? undefined);

  const newCommand = useFrozenSubmission<FrozenDelivery>();
  const endCommand = useFrozenSubmission<FrozenEnd>();
  const locked = newCommand.outcome !== "editing" || endCommand.outcome !== "editing";
  useReportCommandLocked(locked ? "submitting" : "editing", onLockedChange);

  const [newOpen, setNewOpen] = useState(false);
  const [newReceipt, setNewReceipt] = useState<{ delivery: WaterDeliveryEventRead; route: string } | null>(null);
  const [endFlow, setEndFlow] = useState<EndFlowState | null>(null);
  const [endReceipt, setEndReceipt] = useState<WaterDeliveryEventRead | null>(null);
  const [staleNotice, setStaleNotice] = useState<string | null>(null);
  // `?panel=end` (from the hub's "End Delivery" link) opens the End flow
  // once for the selected ongoing row; afterwards the rail is local state.
  const [endRequested, setEndRequested] = useState(searchParams.get("panel") === "end");

  const uoms = uomsQuery.data ?? [];
  const uomCode = (id: string | null) => (id ? uoms.find((u) => u.id === id)?.code ?? "" : "");
  const rows = orderDeliveries(deliveriesQuery.data ?? []);
  // Authoritative detail read first; the list row only while it loads.
  const detail = detailQuery.data ?? rows.find((d) => d.id === selected);

  function contextFor(d: WaterDeliveryEventRead): DeliveryContext {
    return {
      deliveryId: d.id,
      route: routeLabel(d),
      start: formatDateTimeWithZoneLabel(d.effective_start),
      volume: d.delivered_volume ? `${d.delivered_volume} ${uomCode(d.delivered_volume_uom_id)}` : "Not measured",
      mix: d.nutrient_mix_id ? "Related Mix recorded" : "No related Mix",
    };
  }

  function openEnd(d: WaterDeliveryEventRead) {
    setEndReceipt(null);
    setStaleNotice(null);
    setEndFlow({ context: contextFor(d), step: "configure", endLocal: nowAsLocalInput(), note: "", formError: null });
  }
  if (endRequested && detail && detail.effective_end === null && !endFlow) {
    setEndRequested(false);
    openEnd(detail);
  }

  function select(id: string) {
    if (locked) return;
    setSelected(id);
    setNewOpen(false);
    setNewReceipt(null);
    setEndFlow(null);
    setEndReceipt(null);
    setStaleNotice(null);
  }

  function submitNew(draft: Parameters<Parameters<typeof NewDeliveryFlow>[0]["onSubmit"]>[0]) {
    const frozen =
      newCommand.outcome === "uncertain"
        ? newCommand.retry()
        : newCommand.submit((id) => ({ ...draft, payload: { ...draft.payload, client_command_id: id } }));
    if (!frozen) return;
    const result = recordDelivery.mutateAsync(frozen.payload);
    result.then((delivery) => {
      setNewReceipt({ delivery, route: frozen.route });
      setNewOpen(false);
    }, () => undefined);
    settleFrozenAttempt(newCommand, result);
  }

  function reviewEnd() {
    if (!endFlow) return;
    const iso = localInputToIso(endFlow.endLocal);
    if (!iso) return setEndFlow({ ...endFlow, formError: "Enter the end time." });
    setEndFlow({ ...endFlow, formError: null, step: "review" });
  }

  function submitEnd() {
    if (!endFlow) return;
    const frozen =
      endCommand.outcome === "uncertain"
        ? endCommand.retry()
        : endCommand.submit((id) => ({
            ...endFlow.context,
            // Frozen ONCE, from the operator-confirmed value -- never regenerated.
            payload: { effective_end: localInputToIso(endFlow.endLocal) as string, note: endFlow.note.trim() || null, client_command_id: id },
          }));
    if (!frozen) return;
    const result = endDelivery.mutateAsync({ deliveryId: frozen.deliveryId, payload: frozen.payload });
    result.then(
      (delivery) => {
        // The 201 response IS the receipt -- no follow-up read needed.
        setEndReceipt(delivery);
        setEndFlow(null);
      },
      (error) => {
        if (error instanceof AppError && error.kind === "conflict") {
          // Another command already ended it (or this screen was stale):
          // show the authoritative state; never auto-submit anything.
          setEndFlow(null);
          setStaleNotice(`${error.message}. Showing the delivery's current recorded state.`);
          void detailQuery.refetch();
          void deliveriesQuery.refetch();
        } else if (error instanceof AppError && error.kind === "invalid_request") {
          setEndFlow((f) => (f ? { ...f, step: "configure" } : f));
        }
      },
    );
    settleFrozenAttempt(endCommand, result);
  }

  let list;
  if (deliveriesQuery.isLoading && !deliveriesQuery.data) list = <LoadingSkeleton rows={6} label="Loading deliveries" />;
  else if (deliveriesQuery.isError && !deliveriesQuery.data) list = <ErrorState error={deliveriesQuery.error} onRetry={() => deliveriesQuery.refetch()} />;
  else if (rows.length === 0) list = <EmptyState title="No deliveries recorded yet" description="Use New delivery to record the first one." />;
  else {
    const ongoingCount = rows.filter((d) => d.effective_end === null).length;
    list = (
      <fieldset disabled={locked} className="min-w-0">
        <BoundedDataRegion
          label="Irrigation deliveries"
          footer={
            <span className="text-xs text-wl-text-secondary">
              {ongoingCount} ongoing · {rows.length - ongoingCount} ended · times in your local time
              {deliveriesQuery.isError ? " · could not refresh — showing previously loaded data" : ""}
            </span>
          }
        >
          <QueueList label="Irrigation deliveries">
            {rows.map((d) => (
              <QueueRow
                key={d.id}
                isSelected={d.id === selected}
                onSelect={() => select(d.id)}
                title={routeLabel(d)}
                context={`${formatDateTime(d.effective_start)} – ${d.effective_end ? formatDateTime(d.effective_end) : "ongoing"} · ${d.delivered_volume ? `${d.delivered_volume} ${uomCode(d.delivered_volume_uom_id)}` : "Not measured"}`}
                status={<StatusBadge label={d.effective_end ? "Ended" : "Ongoing"} tone={d.effective_end ? "closed" : "attention"} />}
                meta={d.effective_end ? undefined : <span className="hidden sm:inline">Next: End Delivery</span>}
              />
            ))}
          </QueueList>
        </BoundedDataRegion>
      </fieldset>
    );
  }

  let rail;
  if (newReceipt) {
    rail = (
      <div className={cardClass}>
        <NewDeliveryReceipt
          delivery={newReceipt.delivery}
          route={newReceipt.route}
          onDone={() => setNewReceipt(null)}
          onSelect={() => { const id = newReceipt.delivery.id; setNewReceipt(null); select(id); }}
        />
      </div>
    );
  } else if (newOpen || newCommand.outcome !== "editing") {
    rail = (
      <div className={cardClass}>
        <NewDeliveryFlow
          reservoirs={reservoirsQuery.data ?? []}
          circuits={circuitsQuery.data ?? []}
          volumeUoms={uoms.filter((u) => u.quantity_kind === "volume")}
          links={linksQuery.data}
          linksUnavailable={linksQuery.isError}
          command={newCommand}
          onSubmit={submitNew}
          onCancel={() => setNewOpen(false)}
        />
      </div>
    );
  } else if (endReceipt) {
    rail = (
      <div className={cardClass}>
        <EndDeliveryReceipt delivery={endReceipt} onDone={() => setEndReceipt(null)} />
      </div>
    );
  } else if (endFlow || endCommand.outcome !== "editing") {
    const flow = endFlow ?? {
      context: endCommand.frozenPayload as FrozenEnd, step: "review" as const, endLocal: "", note: "", formError: null,
    };
    rail = (
      <div className={cardClass}>
        <EndDeliveryFlow
          flow={flow}
          command={endCommand}
          onChange={(patch) => setEndFlow((f) => (f ? { ...f, ...patch } : f))}
          onReview={reviewEnd}
          onSubmit={submitEnd}
          onBack={() => setEndFlow((f) => (f ? { ...f, step: "configure" } : f))}
          onClose={() => setEndFlow(null)}
        />
      </div>
    );
  } else if (selected && detail) {
    const ongoing = detail.effective_end === null;
    rail = (
      <InspectorShell
        title={routeLabel(detail)}
        subtitle={ongoing ? "Ongoing delivery" : "Ended delivery"}
        status={<StatusBadge label={ongoing ? "Ongoing" : "Ended"} tone={ongoing ? "attention" : "closed"} />}
        onClose={() => setSelected(null)}
      >
        {staleNotice && <p role="alert" className="rounded-lg bg-wl-hold-bg px-3 py-2 text-xs text-wl-hold-fg">{staleNotice}</p>}
        <FactList>
          <Fact label="Start">{formatDateTimeWithZoneLabel(detail.effective_start)}</Fact>
          <Fact label="End">
            {detail.effective_end ? formatDateTimeWithZoneLabel(detail.effective_end) : "Ongoing — no end recorded"}
          </Fact>
          <Fact label="Measured volume">{detail.delivered_volume ? `${detail.delivered_volume} ${uomCode(detail.delivered_volume_uom_id)}` : "Not measured"}</Fact>
          <Fact label="Related Mix">{detail.nutrient_mix_id ? "Related Mix recorded" : "No related Mix"}</Fact>
          {detail.end_source && <Fact label="End source">{detail.end_source === "END_EVENT" ? "End Delivery command" : "Recorded at creation"}</Fact>}
          {detail.end_note && <Fact label="End note">{detail.end_note}</Fact>}
          <Fact label="Notes">{detail.notes ?? "—"}</Fact>
        </FactList>
        {detailQuery.isError && <p className="text-xs text-wl-text-tertiary">Could not refresh this delivery — showing the list&apos;s copy.</p>}
        <details className="text-xs text-wl-text-secondary">
          <summary className="cursor-pointer">Provenance</summary>
          <p className="font-mono">Delivery {detail.id}</p>
          {detail.water_delivery_end_event_id && <p className="font-mono">End event {detail.water_delivery_end_event_id}</p>}
        </details>
        {ongoing && (
          <StickyActionBar>
            <Button variant="primary" className="min-h-11 w-full" onClick={() => openEnd(detail)}>
              End Delivery
            </Button>
          </StickyActionBar>
        )}
      </InspectorShell>
    );
  } else {
    rail = <InspectorEmptyState label="Select a delivery to see it and its next action, or start a new delivery." />;
  }

  return (
    <SplitWorkspace
      main={
        <div className="flex min-w-0 flex-col gap-2">
          <div className="flex items-center justify-between gap-2">
            <h2 className="text-sm font-semibold text-wl-text">Ongoing first, then recently ended</h2>
            <Button
              variant="secondary"
              className="min-h-11"
              disabled={locked}
              onClick={() => { setNewOpen(true); setNewReceipt(null); setEndFlow(null); setEndReceipt(null); }}
            >
              New delivery
            </Button>
          </div>
          {list}
        </div>
      }
      rail={rail}
    />
  );
}

type FrozenReservoirEvent = {
  reservoirId: string;
  reservoirLabel: string;
  quantityLabel: string;
  itemLabel: string;
  payload: ReservoirEventCreate;
};

/** Reservoir events mode: recent history (main) + the guided command (rail). */
function ReservoirEventsMode({ farmId, onLockedChange }: { farmId: string; onLockedChange: (locked: boolean) => void }) {
  const reservoirsQuery = useReservoirs(farmId);
  const eventsQuery = useReservoirEventsForFarm(farmId);
  const uomsQuery = useUoms();
  const itemsQuery = useInventoryItems({ status: "active" });
  const recordEvent = useRecordReservoirEvent(farmId);
  const command = useFrozenSubmission<FrozenReservoirEvent>();
  const locked = command.outcome !== "editing";
  useReportCommandLocked(command.outcome, onLockedChange);

  const [reservoirId, setReservoirId] = useState("");
  const [eventType, setEventType] = useState("");
  const [timingMode, setTimingMode] = useState<TimingMode>("now");
  const [customTime, setCustomTime] = useState("");
  const [quantity, setQuantity] = useState("");
  const [uomId, setUomId] = useState("");
  const [itemId, setItemId] = useState("");
  const [notes, setNotes] = useState("");
  const [step, setStep] = useState<"configure" | "review">("configure");
  const [formError, setFormError] = useState<string | null>(null);
  const [draft, setDraft] = useState<Omit<FrozenReservoirEvent, "payload"> & { payload: Omit<ReservoirEventCreate, "client_command_id"> } | null>(null);
  const [receipt, setReceipt] = useState<{ event: ReservoirEventRead; frozen: FrozenReservoirEvent } | null>(null);

  const reservoirs = reservoirsQuery.data ?? [];
  const uoms = uomsQuery.data ?? [];
  const items = itemsQuery.data ?? [];
  const reservoirById = new Map(reservoirs.map((r) => [r.id, r]));
  const uomById = new Map(uoms.map((u) => [u.id, u]));
  const itemById = new Map(items.map((i) => [i.id, i]));
  const rows = [...(eventsQuery.data ?? [])].sort((a, b) => new Date(b.effective_at).getTime() - new Date(a.effective_at).getTime());

  function review() {
    setFormError(null);
    const reservoir = reservoirById.get(reservoirId);
    if (!reservoir || !eventType) return setFormError("Choose the Reservoir / Tank and the event type.");
    if (quantity.trim() && !uomId) return setFormError("Choose the unit for the quantity.");
    const effectiveAt = timingMode === "custom" ? localInputToIso(customTime) : null;
    if (timingMode === "custom" && !effectiveAt) return setFormError("Enter the custom time, or choose Now (server time).");
    setDraft({
      reservoirId: reservoir.id,
      reservoirLabel: entityLabel(reservoir) ?? "",
      quantityLabel: quantity.trim() ? `${quantity.trim()} ${uomById.get(uomId)?.code ?? ""}` : "Not recorded",
      itemLabel: itemId ? entityLabel(itemById.get(itemId)) ?? "label unavailable" : "Not linked to Store",
      payload: {
        event_type: eventType,
        effective_at: effectiveAt,
        quantity: quantity.trim() || null,
        quantity_uom_id: quantity.trim() ? uomId : null,
        inventory_item_id: itemId || null,
        notes: notes.trim() || null,
      },
    });
    setStep("review");
  }

  function submit() {
    const frozen =
      command.outcome === "uncertain"
        ? command.retry()
        : draft
          ? command.submit((id) => ({ ...draft, payload: { ...draft.payload, client_command_id: id } }))
          : null;
    if (!frozen) return;
    const result = recordEvent.mutateAsync({ reservoirId: frozen.reservoirId, payload: frozen.payload });
    result.then((event) => setReceipt({ event, frozen }), () => undefined);
    settleFrozenAttempt(command, result);
  }

  function recordAnother() {
    setReceipt(null);
    setDraft(null);
    setStep("configure");
    setQuantity("");
    setItemId("");
    setNotes("");
  }

  let rail;
  if (receipt) {
    rail = (
      <section aria-label="Reservoir event receipt" className={`${cardClass} flex flex-col gap-3`}>
        <p role="status" className="text-sm font-semibold text-wl-grow-fg">Reservoir event recorded — confirmed by the server.</p>
        <FactList>
          <Fact label="Reservoir / Tank">{receipt.frozen.reservoirLabel}</Fact>
          <Fact label="Event">{humanizeEnumCode(receipt.event.event_type)}</Fact>
          <Fact label="Effective (server)">{formatDateTimeWithZoneLabel(receipt.event.effective_at)}</Fact>
          <Fact label="Quantity">{receipt.frozen.quantityLabel}</Fact>
          <Fact label="Event ID"><span className="font-mono text-xs">{receipt.event.id}</span></Fact>
        </FactList>
        <p className="text-xs text-wl-text-secondary">
          This event records no resulting pH or EC. To record the observed result, take a separate Measurement.
        </p>
        <div className="flex flex-wrap gap-2">
          <Link href={`/farms/${farmId}/water/measurements`} className={linkButtonClass}>Record a measurement</Link>
          <Button variant="primary" className="min-h-11" onClick={recordAnother}>Record another event</Button>
        </div>
      </section>
    );
  } else {
    const shown = command.frozenPayload ?? (draft ? { ...draft, payload: { ...draft.payload, client_command_id: "" } } : null);
    const errorLine = commandErrorLine(command.error, command.outcome === "uncertain");
    rail =
      (step === "review" || locked) && shown ? (
        <section aria-label="Review reservoir event" className={`${cardClass} flex flex-col gap-3`}>
          <h3 className="text-sm font-semibold text-wl-text">Review: reservoir event</h3>
          <FactList>
            <Fact label="Reservoir / Tank">{shown.reservoirLabel}</Fact>
            <Fact label="Event">{humanizeEnumCode(shown.payload.event_type)}</Fact>
            <Fact label="Effective time">{shown.payload.effective_at ? formatDateTimeWithZoneLabel(shown.payload.effective_at) : "Now (server time)"}</Fact>
            <Fact label="Actual quantity">{shown.quantityLabel}</Fact>
            <Fact label="Inventory Item">{shown.itemLabel}</Fact>
            <Fact label="Notes">{shown.payload.notes ?? "—"}</Fact>
          </FactList>
          <StickyActionBar blockers={<BlockerList lines={[errorLine]} />}>
            <div className="flex gap-2">
              <Button variant="secondary" className="min-h-11" onClick={() => setStep("configure")} disabled={locked}>Back to edit</Button>
              <Button variant="primary" className="min-h-11 flex-1" onClick={submit} disabled={command.outcome === "submitting"}>
                {command.outcome === "submitting" ? "Recording…" : command.outcome === "uncertain" ? "Retry" : "Record event"}
              </Button>
            </div>
          </StickyActionBar>
        </section>
      ) : (
        <section aria-label="Record reservoir event" className={`${cardClass} flex flex-col gap-3`}>
          <h3 className="text-sm font-semibold text-wl-text">Record a reservoir event</h3>
          <label className={labelClass}>
            <span className={labelTextClass}>Reservoir / Tank</span>
            <select className={inputClass} value={reservoirId} onChange={(e) => setReservoirId(e.target.value)}>
              <option value="">Select a Reservoir / Tank…</option>
              {reservoirs.map((r) => <option key={r.id} value={r.id}>{entityLabel(r)}</option>)}
            </select>
          </label>
          <label className={labelClass}>
            <span className={labelTextClass}>Event type</span>
            <select className={inputClass} value={eventType} onChange={(e) => setEventType(e.target.value)}>
              <option value="">Select an event…</option>
              {RESERVOIR_EVENT_TYPES.map((t) => <option key={t} value={t}>{humanizeEnumCode(t)}</option>)}
            </select>
          </label>
          <TimingField legend="Effective time" mode={timingMode} custom={customTime} onModeChange={setTimingMode} onCustomChange={setCustomTime} />
          <div className="grid grid-cols-2 gap-2">
            <label className={labelClass}>
              <span className={labelTextClass}>Actual quantity (optional)</span>
              <input className={inputClass} inputMode="decimal" value={quantity} onChange={(e) => setQuantity(e.target.value)} />
            </label>
            <label className={labelClass}>
              <span className={labelTextClass}>Unit</span>
              <select className={inputClass} value={uomId} onChange={(e) => setUomId(e.target.value)}>
                <option value="">Unit…</option>
                {uoms.map((u) => <option key={u.id} value={u.id}>{u.code}</option>)}
              </select>
            </label>
          </div>
          <label className={labelClass}>
            <span className={labelTextClass}>Inventory Item (optional reference)</span>
            <select className={inputClass} value={itemId} onChange={(e) => setItemId(e.target.value)}>
              <option value="">Not linked to Store</option>
              {items.map((i) => <option key={i.id} value={i.id}>{entityLabel(i)}</option>)}
            </select>
          </label>
          <label className={labelClass}>
            <span className={labelTextClass}>Notes (optional)</span>
            <textarea className={`${inputClass} min-h-16 py-2`} value={notes} onChange={(e) => setNotes(e.target.value)} />
          </label>
          <p className="text-xs text-wl-text-tertiary">No resulting pH/EC or dosage is inferred — record a Measurement for the observed result.</p>
          <StickyActionBar blockers={<BlockerList lines={[formError, errorLine]} />}>
            <Button variant="primary" className="min-h-11 w-full" onClick={review}>Review event</Button>
          </StickyActionBar>
        </section>
      );
  }

  let main;
  if (eventsQuery.isLoading && !eventsQuery.data) main = <LoadingSkeleton rows={6} label="Loading reservoir events" />;
  else if (eventsQuery.isError && !eventsQuery.data) main = <ErrorState error={eventsQuery.error} onRetry={() => eventsQuery.refetch()} />;
  else if (rows.length === 0) main = <EmptyState title="No reservoir events recorded yet" />;
  else {
    main = (
      <BoundedDataRegion label="Recent reservoir events" footer={<span className="text-xs text-wl-text-secondary">{rows.length} event(s), newest first</span>}>
        <ul className="divide-y divide-wl-border">
          {rows.map((ev) => (
            <li key={ev.id} className="flex min-h-11 flex-wrap items-center justify-between gap-2 px-3.5 py-2 text-sm">
              <span className="min-w-0">
                <span className="font-medium text-wl-text">{humanizeEnumCode(ev.event_type)}</span>{" "}
                <span className="text-wl-text-secondary">· {entityLabel(reservoirById.get(ev.reservoir_id)) ?? "Reservoir label unavailable"}</span>
                <span className="block text-xs text-wl-text-secondary">
                  {ev.quantity ? `${ev.quantity} ${ev.quantity_uom_id ? uomById.get(ev.quantity_uom_id)?.code ?? "" : ""}` : "No quantity recorded"}
                  {ev.inventory_item_id ? ` · ${entityLabel(itemById.get(ev.inventory_item_id)) ?? "Inventory Item label unavailable"}` : ""}
                  {ev.notes ? ` · ${ev.notes}` : ""}
                </span>
              </span>
              <span className="text-xs text-wl-text-secondary">{formatDateTimeWithZoneLabel(ev.effective_at)}</span>
            </li>
          ))}
        </ul>
      </BoundedDataRegion>
    );
  }

  return <SplitWorkspace main={main} rail={rail} />;
}

/** UX-OPS-001D: durable URL-backed modes (`?view=`), each with ONE bounded
 * list/main region plus ONE guided rail -- never both command forms or
 * both histories stacked. */
export default function WaterDeliveryPage() {
  const { farmId } = useParams<{ farmId: string }>();
  const { data: farm } = useFarm(farmId);
  const { view, setView } = useViewState<View>({ views: VIEWS, defaultView: "deliveries" });
  const [locked, setLocked] = useState(false);

  return (
    <div>
      <WaterWorkspaceHeader
        farmId={farmId}
        title="Delivery"
        description={farm ? `Irrigation deliveries and reservoir events for ${farm.name}` : undefined}
        locked={locked}
      />
      <div className="mb-3">
        <ViewTabs
          items={[
            { value: "deliveries", label: "Irrigation deliveries" },
            { value: "reservoir-events", label: "Reservoir events" },
          ]}
          active={view}
          onChange={setView}
          disabled={locked}
        />
      </div>
      {view === "deliveries" ? (
        <DeliveriesMode farmId={farmId} onLockedChange={setLocked} />
      ) : (
        <ReservoirEventsMode farmId={farmId} onLockedChange={setLocked} />
      )}
    </div>
  );
}
