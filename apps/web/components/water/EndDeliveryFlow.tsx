"use client";

import { StickyActionBar } from "@/components/layout/StickyActionBar";
import { Button } from "@/components/ui/Button";
import {
  BlockerList,
  Fact,
  FactList,
  commandErrorLine,
  inputClass,
  labelClass,
  labelTextClass,
} from "@/components/water/waterUi";
import type { WaterDeliveryEventEnd, WaterDeliveryEventRead } from "@/lib/api/client";
import type { UseFrozenSubmissionResult } from "@/lib/commands/frozenSubmission";
import { formatDateTimeWithZoneLabel } from "@/lib/format/datetime";

/** Immutable read-only context the End Delivery flow shows -- captured
 * with the command so Review/Retry never re-derive it from a refetch. */
export type DeliveryContext = {
  deliveryId: string;
  route: string;
  start: string;
  volume: string;
  mix: string;
};

export type FrozenEnd = DeliveryContext & { payload: WaterDeliveryEventEnd };

export type EndFlowState = {
  context: DeliveryContext;
  step: "configure" | "review";
  /** Proposed ONCE (operator's local now) when the flow opens -- visible,
   * editable, confirmed on Review, and never regenerated after. */
  endLocal: string;
  note: string;
  formError: string | null;
};

export function EndDeliveryContextFacts({ context }: { context: DeliveryContext }) {
  return (
    <FactList>
      <Fact label="Reservoir → Circuit">{context.route}</Fact>
      <Fact label="Started">{context.start}</Fact>
      <Fact label="Status">Ongoing — no end recorded yet</Fact>
      <Fact label="Measured volume">{context.volume}</Fact>
      <Fact label="Related Mix">{context.mix}</Fact>
    </FactList>
  );
}

/** UX-OPS-001D0 End Delivery: the only editable facts are the required end
 * time and an optional note. Command + flow state are owned by the parent
 * (above selection), passed in here. */
export function EndDeliveryFlow({
  flow,
  command,
  onChange,
  onReview,
  onSubmit,
  onBack,
  onClose,
}: {
  flow: EndFlowState;
  command: UseFrozenSubmissionResult<FrozenEnd>;
  onChange: (patch: Partial<EndFlowState>) => void;
  onReview: () => void;
  onSubmit: () => void;
  onBack: () => void;
  onClose: () => void;
}) {
  const locked = command.outcome !== "editing";
  const frozen = command.frozenPayload;
  const context = frozen ?? flow.context;
  const errorLine = commandErrorLine(command.error, command.outcome === "uncertain");

  if (flow.step === "review" || locked) {
    const endIso = frozen?.payload.effective_end ?? null;
    return (
      <section aria-label="Review End Delivery" className="flex flex-col gap-3">
        <h3 className="text-sm font-semibold text-wl-text">Review: End Delivery</h3>
        <EndDeliveryContextFacts context={context} />
        <FactList>
          <Fact label="End time to record">
            {endIso ? formatDateTimeWithZoneLabel(endIso) : formatDateTimeWithZoneLabel(new Date(flow.endLocal).toISOString())}
          </Fact>
          <Fact label="Note">{(frozen ? frozen.payload.note : flow.note.trim() || null) ?? "—"}</Fact>
        </FactList>
        <p className="rounded-lg bg-wl-surface-sunken px-3 py-2 text-xs text-wl-text-secondary">
          The original Delivery record stays unchanged; this appends a separate End Delivery fact. No final volume is being recorded.
        </p>
        <StickyActionBar blockers={<BlockerList lines={[errorLine]} />}>
          <div className="flex gap-2">
            <Button variant="secondary" className="min-h-11" onClick={onBack} disabled={locked}>
              Back to edit
            </Button>
            <Button variant="primary" className="min-h-11 flex-1" onClick={onSubmit} disabled={command.outcome === "submitting"}>
              {command.outcome === "submitting" ? "Ending…" : command.outcome === "uncertain" ? "Retry" : "End Delivery"}
            </Button>
          </div>
        </StickyActionBar>
      </section>
    );
  }

  return (
    <section aria-label="End Delivery" className="flex flex-col gap-3">
      <h3 className="text-sm font-semibold text-wl-text">End Delivery</h3>
      <EndDeliveryContextFacts context={context} />
      <label className={labelClass}>
        <span className={labelTextClass}>End time (required — proposed as your current time; edit if needed)</span>
        <input
          type="datetime-local"
          className={inputClass}
          value={flow.endLocal}
          onChange={(e) => onChange({ endLocal: e.target.value })}
        />
      </label>
      <label className={labelClass}>
        <span className={labelTextClass}>Note (optional)</span>
        <textarea className={`${inputClass} min-h-16 py-2`} value={flow.note} onChange={(e) => onChange({ note: e.target.value })} />
      </label>
      <StickyActionBar blockers={<BlockerList lines={[flow.formError, errorLine]} />}>
        <div className="flex gap-2">
          <Button variant="secondary" className="min-h-11" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" className="min-h-11 flex-1" onClick={onReview}>
            Review End Delivery
          </Button>
        </div>
      </StickyActionBar>
    </section>
  );
}

export function EndDeliveryReceipt({ delivery, onDone }: { delivery: WaterDeliveryEventRead; onDone: () => void }) {
  return (
    <section aria-label="End Delivery receipt" className="flex flex-col gap-3">
      <p role="status" className="text-sm font-semibold text-wl-grow-fg">Delivery ended — confirmed by the server.</p>
      <FactList>
        <Fact label="Resolved end">{formatDateTimeWithZoneLabel(delivery.effective_end)}</Fact>
        <Fact label="End source">{delivery.end_source === "END_EVENT" ? "End Delivery command (END_EVENT)" : delivery.end_source ?? "—"}</Fact>
        <Fact label="End event ID">
          <span className="font-mono text-xs">{delivery.water_delivery_end_event_id ?? "—"}</span>
        </Fact>
        <Fact label="End note">{delivery.end_note ?? "—"}</Fact>
      </FactList>
      <Button variant="secondary" className="min-h-11" onClick={onDone}>
        Done
      </Button>
    </section>
  );
}
