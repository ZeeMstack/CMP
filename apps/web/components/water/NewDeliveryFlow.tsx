"use client";

import { useState } from "react";

import { StickyActionBar } from "@/components/layout/StickyActionBar";
import { Button } from "@/components/ui/Button";
import {
  BlockerList,
  Fact,
  FactList,
  TimingField,
  commandErrorLine,
  entityLabel,
  inputClass,
  labelClass,
  labelTextClass,
  localInputToIso,
  type TimingMode,
} from "@/components/water/waterUi";
import type {
  IrrigationCircuitRead,
  ReservoirRead,
  TopologyLinkRead,
  UnitOfMeasureRead,
  WaterDeliveryEventCreate,
  WaterDeliveryEventRead,
} from "@/lib/api/client";
import type { UseFrozenSubmissionResult } from "@/lib/commands/frozenSubmission";
import { formatDateTimeWithZoneLabel } from "@/lib/format/datetime";
import { useMixesForReservoir } from "@/lib/query/hooks";

export type FrozenDelivery = {
  route: string;
  volumeLabel: string;
  mixLabel: string;
  payload: WaterDeliveryEventCreate;
};

/** Truthful context only: which configured Reservoir -> Circuit link (if
 * any) is effective at the chosen instant. Never an authorization rule --
 * the server validates the command; exposure still needs a complete route. */
export function connectionStatus(
  links: TopologyLinkRead[] | undefined,
  reservoirId: string,
  circuitId: string,
  atMs: number,
): { kind: "unavailable" | "connected" | "not_connected"; since?: string } {
  if (!links) return { kind: "unavailable" };
  const match = links.find(
    (l) =>
      l.reservoir_id === reservoirId &&
      l.irrigation_circuit_id === circuitId &&
      new Date(l.effective_from).getTime() <= atMs &&
      (l.effective_to === null || new Date(l.effective_to).getTime() > atMs),
  );
  return match ? { kind: "connected", since: match.effective_from } : { kind: "not_connected" };
}

export function NewDeliveryFlow({
  reservoirs,
  circuits,
  volumeUoms,
  links,
  linksUnavailable,
  command,
  onSubmit,
  onCancel,
}: {
  reservoirs: ReservoirRead[];
  circuits: IrrigationCircuitRead[];
  volumeUoms: UnitOfMeasureRead[];
  links: TopologyLinkRead[] | undefined;
  linksUnavailable: boolean;
  command: UseFrozenSubmissionResult<FrozenDelivery>;
  onSubmit: (draft: Omit<FrozenDelivery, "payload"> & { payload: Omit<WaterDeliveryEventCreate, "client_command_id"> }) => void;
  onCancel: () => void;
}) {
  const [reservoirId, setReservoirId] = useState("");
  const [circuitId, setCircuitId] = useState("");
  const [startMode, setStartMode] = useState<TimingMode>("now");
  const [startLocal, setStartLocal] = useState("");
  const [closedAtCreation, setClosedAtCreation] = useState(false);
  const [endLocal, setEndLocal] = useState("");
  const [volume, setVolume] = useState("");
  const [volumeUomId, setVolumeUomId] = useState("");
  const [mixId, setMixId] = useState("");
  const [notes, setNotes] = useState("");
  const [step, setStep] = useState<"configure" | "review">("configure");
  const [formError, setFormError] = useState<string | null>(null);
  const [draft, setDraft] = useState<Parameters<typeof onSubmit>[0] | null>(null);

  const mixesQuery = useMixesForReservoir(reservoirId || undefined);
  const locked = command.outcome !== "editing";
  const errorLine = commandErrorLine(command.error, command.outcome === "uncertain");

  const reservoir = reservoirs.find((r) => r.id === reservoirId);
  const circuit = circuits.find((c) => c.id === circuitId);
  const startIso = startMode === "custom" ? localInputToIso(startLocal) : null;
  // "Now" is only a display instant for the connection hint -- the command
  // itself sends `effective_start: null` (server time).
  const [openedAtMs] = useState(() => Date.now());
  const status =
    reservoir && circuit
      ? linksUnavailable
        ? { kind: "unavailable" as const }
        : connectionStatus(links, reservoir.id, circuit.id, startIso ? new Date(startIso).getTime() : openedAtMs)
      : null;

  function review() {
    setFormError(null);
    if (!reservoir || !circuit) return setFormError("Choose the source Reservoir / Tank and the Irrigation Circuit.");
    if (startMode === "custom" && !startIso) return setFormError("Enter the custom start time, or choose Now (server time).");
    const endIso = closedAtCreation ? localInputToIso(endLocal) : null;
    if (closedAtCreation && !endIso) return setFormError("Enter the end time, or record the delivery as ongoing.");
    if (volume.trim() && !volumeUomId) return setFormError("Choose the unit for the measured volume.");
    const mix = (mixesQuery.data ?? []).find((m) => m.id === mixId);
    const uom = volumeUoms.find((u) => u.id === volumeUomId);
    const next = {
      route: `${entityLabel(reservoir)} → ${entityLabel(circuit)}`,
      volumeLabel: volume.trim() ? `${volume.trim()} ${uom?.code ?? ""}` : "Not measured",
      mixLabel: mix ? `Mix of ${formatDateTimeWithZoneLabel(mix.effective_at)}` : "No related Mix",
      payload: {
        reservoir_id: reservoir.id,
        irrigation_circuit_id: circuit.id,
        effective_start: startIso,
        effective_end: endIso,
        // Blank volume stays null (not measured) -- never zero.
        delivered_volume: volume.trim() || null,
        delivered_volume_uom_id: volume.trim() ? volumeUomId : null,
        nutrient_mix_id: mix?.id ?? null,
        notes: notes.trim() || null,
      },
    };
    setDraft(next);
    setStep("review");
  }

  const shown = command.frozenPayload ?? (draft ? { ...draft, payload: { ...draft.payload, client_command_id: "" } } : null);
  if ((step === "review" || locked) && shown) {
    const p = shown.payload;
    return (
      <section aria-label="Review new delivery" className="flex flex-col gap-3">
        <h3 className="text-sm font-semibold text-wl-text">Review: new delivery</h3>
        <FactList>
          <Fact label="Reservoir → Circuit">{shown.route}</Fact>
          <Fact label="Start">{p.effective_start ? formatDateTimeWithZoneLabel(p.effective_start) : "Now (server time)"}</Fact>
          <Fact label="End">{p.effective_end ? formatDateTimeWithZoneLabel(p.effective_end) : "Ongoing — ended later with End Delivery"}</Fact>
          <Fact label="Measured volume">{shown.volumeLabel}</Fact>
          <Fact label="Related Mix">{shown.mixLabel}</Fact>
          <Fact label="Notes">{p.notes ?? "—"}</Fact>
        </FactList>
        <StickyActionBar blockers={<BlockerList lines={[errorLine]} />}>
          <div className="flex gap-2">
            <Button variant="secondary" className="min-h-11" onClick={() => setStep("configure")} disabled={locked}>
              Back to edit
            </Button>
            <Button
              variant="primary"
              className="min-h-11 flex-1"
              disabled={command.outcome === "submitting"}
              onClick={() => (draft ? onSubmit(draft) : undefined)}
            >
              {command.outcome === "submitting" ? "Recording…" : command.outcome === "uncertain" ? "Retry" : "Record delivery"}
            </Button>
          </div>
        </StickyActionBar>
      </section>
    );
  }

  return (
    <section aria-label="New delivery" className="flex flex-col gap-3">
      <h3 className="text-sm font-semibold text-wl-text">New delivery</h3>
      <label className={labelClass}>
        <span className={labelTextClass}>Source Reservoir / Tank</span>
        <select className={inputClass} value={reservoirId} onChange={(e) => { setReservoirId(e.target.value); setMixId(""); }}>
          <option value="">Select a Reservoir / Tank…</option>
          {reservoirs.map((r) => <option key={r.id} value={r.id}>{entityLabel(r)}</option>)}
        </select>
      </label>
      <label className={labelClass}>
        <span className={labelTextClass}>Irrigation Circuit</span>
        <select className={inputClass} value={circuitId} onChange={(e) => setCircuitId(e.target.value)}>
          <option value="">Select a Circuit…</option>
          {circuits.map((c) => <option key={c.id} value={c.id}>{entityLabel(c)}</option>)}
        </select>
      </label>
      {status && (
        <p role="status" data-testid="connection-status" className={`rounded-lg px-3 py-2 text-xs ${status.kind === "connected" ? "bg-wl-surface-sunken text-wl-text-secondary" : "bg-wl-hold-bg text-wl-hold-fg"}`}>
          {status.kind === "connected"
            ? `Configured connection: this Reservoir → Circuit link is effective at the chosen time (since ${formatDateTimeWithZoneLabel(status.since)}).`
            : status.kind === "not_connected"
              ? "No configured Reservoir → Circuit link is effective at the chosen time. The server still decides whether the delivery is valid; exposure needs a complete configured route."
              : "Configured connection status is unavailable right now."}
        </p>
      )}
      <TimingField legend="Start" mode={startMode} custom={startLocal} onModeChange={setStartMode} onCustomChange={setStartLocal} />
      <fieldset className="flex flex-col gap-1.5">
        <legend className={labelTextClass}>End</legend>
        <label className="flex min-h-11 items-center gap-2 text-sm">
          <input type="radio" name="delivery-end" checked={!closedAtCreation} onChange={() => setClosedAtCreation(false)} />
          Ongoing — end it later with End Delivery
        </label>
        <label className="flex min-h-11 items-center gap-2 text-sm">
          <input type="radio" name="delivery-end" checked={closedAtCreation} onChange={() => setClosedAtCreation(true)} />
          Already ended — record its end now
        </label>
        {closedAtCreation && (
          <input type="datetime-local" aria-label="End time" className={inputClass} value={endLocal} onChange={(e) => setEndLocal(e.target.value)} />
        )}
      </fieldset>
      <div className="grid grid-cols-2 gap-2">
        <label className={labelClass}>
          <span className={labelTextClass}>Measured volume</span>
          <input className={inputClass} inputMode="decimal" value={volume} onChange={(e) => setVolume(e.target.value)} placeholder="Blank = not measured" />
        </label>
        <label className={labelClass}>
          <span className={labelTextClass}>Unit</span>
          <select className={inputClass} value={volumeUomId} onChange={(e) => setVolumeUomId(e.target.value)}>
            <option value="">Unit…</option>
            {volumeUoms.map((u) => <option key={u.id} value={u.id}>{u.code}</option>)}
          </select>
        </label>
      </div>
      <label className={labelClass}>
        <span className={labelTextClass}>Related Mix from this Reservoir (optional)</span>
        <select className={inputClass} value={mixId} onChange={(e) => setMixId(e.target.value)} disabled={!reservoirId}>
          <option value="">No related Mix</option>
          {(mixesQuery.data ?? []).map((m) => (
            <option key={m.id} value={m.id}>Mix of {formatDateTimeWithZoneLabel(m.effective_at)}</option>
          ))}
        </select>
      </label>
      <label className={labelClass}>
        <span className={labelTextClass}>Notes (optional)</span>
        <textarea className={`${inputClass} min-h-16 py-2`} value={notes} onChange={(e) => setNotes(e.target.value)} />
      </label>
      <StickyActionBar blockers={<BlockerList lines={[formError, errorLine]} />}>
        <div className="flex gap-2">
          <Button variant="secondary" className="min-h-11" onClick={onCancel}>
            Cancel
          </Button>
          <Button variant="primary" className="min-h-11 flex-1" onClick={review}>
            Review delivery
          </Button>
        </div>
      </StickyActionBar>
    </section>
  );
}

export function NewDeliveryReceipt({
  delivery, route, onSelect, onDone,
}: {
  delivery: WaterDeliveryEventRead;
  route: string;
  onSelect: () => void;
  onDone: () => void;
}) {
  return (
    <section aria-label="Delivery receipt" className="flex flex-col gap-3">
      <p role="status" className="text-sm font-semibold text-wl-grow-fg">Delivery recorded — confirmed by the server.</p>
      <FactList>
        <Fact label="Reservoir → Circuit">{route}</Fact>
        <Fact label="Start (server)">{formatDateTimeWithZoneLabel(delivery.effective_start)}</Fact>
        <Fact label="End">{delivery.effective_end ? formatDateTimeWithZoneLabel(delivery.effective_end) : "Ongoing"}</Fact>
        <Fact label="Measured volume">{delivery.delivered_volume ?? "Not measured"}</Fact>
        <Fact label="Delivery ID"><span className="font-mono text-xs">{delivery.id}</span></Fact>
      </FactList>
      <div className="flex gap-2">
        <Button variant="secondary" className="min-h-11" onClick={onDone}>Done</Button>
        <Button variant="primary" className="min-h-11 flex-1" onClick={onSelect}>Open this delivery</Button>
      </div>
    </section>
  );
}
