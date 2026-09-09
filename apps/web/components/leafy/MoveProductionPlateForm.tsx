"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import { LeafyLocationSelector, type LeafyLocationValue } from "@/components/leafy/LeafyLocationSelector";
import { Button } from "@/components/ui/Button";
import type { ActiveProductionPlateRead, MovementCreate } from "@/lib/api/client";
import { AppError, friendlyMutationErrorMessage } from "@/lib/errors/adapter";
import { useGreenhouseSetupOverview, useLocationPath } from "@/lib/query/hooks";

const errorClass = "text-xs text-red-700";

const EMPTY_DESTINATION: LeafyLocationValue = {
  leafy_greenhouse_id: "", zone_id: "", span_id: "", destination_location_id: "", table_label: "",
  table_capacity: null,
};

/** LEAFY-OPS-002: "Move plate" -- relocates an existing Production
 * Cultivation Plate (with its living plants) from its current Leafy Table
 * to another. A pure physical Movement: reuses the generic Movement
 * command completely unchanged (`occupant: carrier`, `destination:
 * location`), never a biological transplant, split, correction, loss, or
 * Harvest -- Batch identity and living population are never touched by
 * this command. Configure -> Review -> Confirm, matching every other
 * compact operator workflow already established on this page (see
 * `RecordPlantLossForm.tsx`). Destination Greenhouse/Zone/Span default to
 * the Plate's current placement (resolved via the existing generic
 * `/locations/{id}/path` read, section "If source context already
 * identifies GH/Zone/Span, do not ask the operator to reselect") so the
 * operator only has to pick a new Table in the common case of moving
 * within the same Span/Zone; `LeafyLocationSelector`'s own
 * `excludeLocationId` keeps the current Table from ever being offered as
 * its own destination. No date/time or note field -- the ticket's own
 * compact mockup has neither, and a relocation is always "now". */
export function MoveProductionPlateForm({
  farmId,
  plate,
  onSubmit,
  onCancel,
  isSubmitting,
  serverError,
}: {
  farmId: string;
  plate: ActiveProductionPlateRead;
  onSubmit: (payload: MovementCreate, toLabel: string) => void;
  onCancel: () => void;
  isSubmitting: boolean;
  serverError?: AppError | null;
}) {
  const [step, setStep] = useState<"configure" | "review">("configure");
  const [destination, setDestination] = useState<LeafyLocationValue>(EMPTY_DESTINATION);
  const [clientCommandId, setClientCommandId] = useState(() => crypto.randomUUID());
  const lastSubmittedFingerprintRef = useRef<string | null>(null);
  const hasAutoFilledRef = useRef(false);

  const currentLocationId = plate.current_location?.id ?? null;
  const pathQuery = useLocationPath(farmId, currentLocationId);
  const overviewQuery = useGreenhouseSetupOverview(farmId);
  const leafyGreenhouses = useMemo(
    () => (overviewQuery.data ?? []).filter((item) => item.classification === "leafy_greens"),
    [overviewQuery.data],
  );

  // Frozen Leafy hierarchy (Greenhouse -> Zone -> Span -> Table, no
  // shortcuts): a Table's own path is always exactly 4 entries deep, root
  // first -- [Greenhouse, Zone, Span, Table itself]. Only ever runs once
  // (`hasAutoFilledRef`) so a later refetch of this query never clobbers an
  // operator edit already in progress; a ref write belongs in an effect,
  // never read/written directly during render.
  const pathData = pathQuery.data;
  useEffect(() => {
    if (hasAutoFilledRef.current || !pathData || pathData.path.length !== 4) return;
    hasAutoFilledRef.current = true;
    const [greenhouse, zone, span] = pathData.path;
    setDestination((prev) =>
      prev.leafy_greenhouse_id
        ? prev
        : { ...prev, leafy_greenhouse_id: greenhouse.id, zone_id: zone.id, span_id: span.id },
    );
  }, [pathData]);

  // Mirrors every other compact form's established 409 handling: a
  // conflict means the state this draft was built against has changed
  // elsewhere (the Table filled up, the Plate already moved). Forces back
  // to Configure -- the destination selection itself is untouched, so the
  // operator can immediately see and pick a different Table without
  // starting over.
  const [prevServerError, setPrevServerError] = useState(serverError);
  if (serverError !== prevServerError) {
    setPrevServerError(serverError);
    if (serverError?.kind === "conflict") setStep("configure");
  }

  const canReview =
    Boolean(destination.destination_location_id) && destination.destination_location_id !== currentLocationId;

  function confirm() {
    const fingerprint = JSON.stringify({ destination_location_id: destination.destination_location_id });
    let idToUse = clientCommandId;
    if (lastSubmittedFingerprintRef.current !== null && lastSubmittedFingerprintRef.current !== fingerprint) {
      idToUse = crypto.randomUUID();
      setClientCommandId(idToUse);
    }
    lastSubmittedFingerprintRef.current = fingerprint;
    onSubmit(
      {
        client_command_id: idToUse,
        effective_time: new Date().toISOString(),
        occupant: { kind: "carrier", id: plate.carrier_id },
        destination: { kind: "location", id: destination.destination_location_id },
        reason: null,
      },
      destination.table_label,
    );
  }

  if (step === "review") {
    return (
      <div className="flex flex-col gap-3 rounded-xl border border-border-subtle bg-surface p-4">
        <h2 className="font-serif text-base font-semibold text-ink">Review move</h2>
        <p className="text-sm text-ink">{plate.plate_code}</p>
        <p className="text-sm text-ink">
          {plate.current_location?.code ?? "—"} → {destination.table_label || "—"}
        </p>
        <p className="text-sm text-ink-muted">Batch {plate.batch_code}</p>
        {serverError && (
          <p role="alert" className={errorClass}>
            {friendlyMutationErrorMessage(serverError)}
          </p>
        )}
        <div className="flex gap-2">
          <Button type="button" variant="secondary" onClick={() => setStep("configure")} disabled={isSubmitting}>
            Back
          </Button>
          <Button type="button" variant="primary" onClick={confirm} disabled={isSubmitting}>
            {isSubmitting ? "Moving…" : "Confirm move"}
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4 rounded-xl border border-border-subtle bg-surface p-4">
      <div className="flex items-center justify-between">
        <h2 className="font-serif text-base font-semibold text-ink">Move plate — {plate.plate_code}</h2>
        <Button type="button" variant="secondary" onClick={onCancel}>
          Cancel
        </Button>
      </div>

      <dl className="text-sm">
        <div>
          <dt className="text-ink-muted">Current placement</dt>
          <dd className="font-medium text-ink">
            Batch {plate.batch_code} · {plate.plate_code}
            <br />
            {plate.current_location?.ancestry_label ?? "No current Leafy location on record"}
          </dd>
        </div>
      </dl>

      <div className="flex flex-col gap-3">
        <span className="text-sm font-medium text-ink">Move to</span>
        <LeafyLocationSelector
          farmId={farmId}
          leafyGreenhouses={leafyGreenhouses}
          leafyGreenhousesLoading={overviewQuery.isLoading}
          value={destination}
          onChange={setDestination}
          excludeLocationId={currentLocationId}
        />
      </div>

      {serverError && (
        <p role="alert" className={errorClass}>
          {friendlyMutationErrorMessage(serverError)}
        </p>
      )}

      <div>
        <Button type="button" variant="primary" disabled={!canReview} onClick={() => setStep("review")}>
          Review move
        </Button>
      </div>
    </div>
  );
}
