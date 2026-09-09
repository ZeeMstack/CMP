"use client";

import { useRef, useState } from "react";

import { Button } from "@/components/ui/Button";
import type { RecordVinesGrowCubeDispositionCreate, VinesProductionPlacementGrowCubeRead } from "@/lib/api/client";
import { AppError, friendlyMutationErrorMessage } from "@/lib/errors/adapter";
import { VINES_DISPOSITION_REASONS } from "@/lib/validation/vinesProductionDisposition";

const inputClass =
  "min-h-11 w-full rounded-md border border-border-subtle bg-surface px-3 text-sm text-ink focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-600";
const labelClass = "block text-sm font-medium text-ink";
const errorClass = "text-xs text-red-700";

function Field({ label, error, children }: { label: string; error?: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1">
      <span className={labelClass}>{label}</span>
      {children}
      {error && <span className={errorClass}>{error}</span>}
    </label>
  );
}

function nowDateAndTime() {
  const now = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  return {
    date: `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`,
    time: `${pad(now.getHours())}:${pad(now.getMinutes())}`,
  };
}

/** VINES-OPS-002: compact "Record plant loss" panel -- targets specific
 * Grow Cube(s) (one living plant each) inside ONE Grow Bag, never a bare
 * count. Auto-selects the sole living Grow Cube when only one remains
 * (ticket: "If a Grow Bag has only one living Grow Cube, selecting the bag
 * may auto-select that plant"). No camera/barcode scan wiring yet -- compact
 * checkbox multi-select stands in for it (see the ticket's own "or select
 * Grow Bag then affected Grow Cube(s)" allowance). Configure -> review ->
 * confirm, mirroring `RecordPlantLossForm.tsx`'s own established shape. */
export function RecordGrowCubeLossForm({
  growBagCode,
  batchCarrierAssignmentId,
  livingPlantCount,
  growCubes,
  onSubmit,
  onCancel,
  isSubmitting,
  serverError,
}: {
  growBagCode: string;
  batchCarrierAssignmentId: string;
  livingPlantCount: number;
  growCubes: VinesProductionPlacementGrowCubeRead[];
  onSubmit: (payload: RecordVinesGrowCubeDispositionCreate) => void;
  onCancel: () => void;
  isSubmitting: boolean;
  serverError?: AppError | null;
}) {
  const livingCubes = growCubes.filter((c) => c.status === "living");
  const [step, setStep] = useState<"configure" | "review">("configure");
  const [selectedIds, setSelectedIds] = useState<string[]>(livingCubes.length === 1 ? [livingCubes[0].grow_cube.id] : []);
  const [reasonCode, setReasonCode] = useState("");
  const [note, setNote] = useState("");
  const initial = nowDateAndTime();
  const [effectiveDate, setEffectiveDate] = useState(initial.date);
  const [effectiveTimeOfDay, setEffectiveTimeOfDay] = useState(initial.time);
  const [validationError, setValidationError] = useState<string | null>(null);
  const [clientCommandId, setClientCommandId] = useState(() => crypto.randomUUID());
  const lastSubmittedFingerprintRef = useRef<string | null>(null);

  const [prevServerError, setPrevServerError] = useState(serverError);
  if (serverError !== prevServerError) {
    setPrevServerError(serverError);
    if (serverError?.kind === "conflict") setStep("configure");
  }

  function toggle(id: string) {
    setSelectedIds((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));
  }

  function goToReview() {
    if (selectedIds.length === 0) {
      setValidationError("Select at least one affected plant");
      return;
    }
    if (!reasonCode) {
      setValidationError("Reason is required");
      return;
    }
    if (reasonCode === "other" && !note.trim()) {
      setValidationError("A note is required when reason is Other");
      return;
    }
    setValidationError(null);
    setStep("review");
  }

  function confirm() {
    const effectiveTime = new Date(`${effectiveDate}T${effectiveTimeOfDay}`).toISOString();
    const fingerprint = JSON.stringify({
      batch_carrier_assignment_id: batchCarrierAssignmentId,
      grow_cube_carrier_ids: [...selectedIds].sort(),
      reason_code: reasonCode, effective_time: effectiveTime, note: note.trim() || null,
    });
    let idToUse = clientCommandId;
    if (lastSubmittedFingerprintRef.current !== null && lastSubmittedFingerprintRef.current !== fingerprint) {
      idToUse = crypto.randomUUID();
      setClientCommandId(idToUse);
    }
    lastSubmittedFingerprintRef.current = fingerprint;
    onSubmit({
      client_command_id: idToUse, batch_carrier_assignment_id: batchCarrierAssignmentId,
      grow_cube_carrier_ids: selectedIds, reason_code: reasonCode, effective_time: effectiveTime,
      note: note.trim() || null,
    });
  }

  const selectedCodes = growCubes
    .filter((c) => selectedIds.includes(c.grow_cube.id))
    .map((c) => c.grow_cube.code);

  if (step === "review") {
    return (
      <div className="flex flex-col gap-4 rounded-xl border border-border-subtle bg-surface p-4">
        <h2 className="font-serif text-base font-semibold text-ink">Review before recording</h2>
        <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
          <div>
            <dt className="text-ink-muted">Grow Bag</dt>
            <dd className="font-medium text-ink">{growBagCode}</dd>
          </div>
          <div>
            <dt className="text-ink-muted">Current living</dt>
            <dd className="font-medium text-ink">{livingPlantCount.toLocaleString()}</dd>
          </div>
          <div className="col-span-2">
            <dt className="text-ink-muted">Affected plant(s)</dt>
            <dd className="font-medium text-ink">{selectedCodes.join(", ")}</dd>
          </div>
          <div>
            <dt className="text-ink-muted">Resulting living</dt>
            <dd className="font-medium text-ink">{(livingPlantCount - selectedIds.length).toLocaleString()}</dd>
          </div>
          <div>
            <dt className="text-ink-muted">Reason</dt>
            <dd className="font-medium text-ink">
              {VINES_DISPOSITION_REASONS.find((r) => r.code === reasonCode)?.label ?? reasonCode}
            </dd>
          </div>
          <div>
            <dt className="text-ink-muted">Occurred at</dt>
            <dd className="font-medium text-ink">{effectiveDate} {effectiveTimeOfDay}</dd>
          </div>
        </dl>
        {note && (
          <p className="text-sm text-ink-muted">
            Note: <span className="text-ink">{note}</span>
          </p>
        )}
        {livingPlantCount - selectedIds.length === 0 && (
          <p className="text-sm text-ink-muted">
            Current Living will become 0 and the biological assignment will release. The physical Grow Bag remains
            at its current Position.
          </p>
        )}
        {serverError && (
          <p role="alert" className={errorClass}>
            {friendlyMutationErrorMessage(serverError)}
          </p>
        )}
        <div className="flex gap-3">
          <Button type="button" variant="secondary" onClick={() => setStep("configure")} disabled={isSubmitting}>
            Back
          </Button>
          <Button type="button" variant="primary" onClick={confirm} disabled={isSubmitting}>
            {isSubmitting ? "Recording…" : "Confirm"}
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4 rounded-xl border border-border-subtle bg-surface p-4">
      <div className="flex items-center justify-between">
        <h2 className="font-serif text-base font-semibold text-ink">Record Plant Loss — {growBagCode}</h2>
        <Button type="button" variant="secondary" onClick={onCancel}>
          Cancel
        </Button>
      </div>
      <dl className="text-sm">
        <div>
          <dt className="text-ink-muted">Current living</dt>
          <dd className="font-medium text-ink">{livingPlantCount.toLocaleString()}</dd>
        </div>
      </dl>

      <fieldset className="flex flex-col gap-2">
        <legend className={labelClass}>Affected plant(s)</legend>
        <div className="flex flex-col gap-1">
          {growCubes.map((c) => {
            const removed = c.status === "removed";
            return (
              <label
                key={c.grow_cube.id}
                className={`flex items-center gap-2 rounded-md border border-border-subtle px-3 py-2 text-sm ${removed ? "opacity-50" : "cursor-pointer hover:bg-surface-subtle"}`}
              >
                <input
                  type="checkbox" disabled={removed} checked={selectedIds.includes(c.grow_cube.id)}
                  onChange={() => toggle(c.grow_cube.id)}
                />
                <span className="text-ink">{c.grow_cube.code}</span>
                {removed && <span className="text-xs text-ink-muted">already removed{c.disposition ? ` — ${c.disposition.reason_code}` : ""}</span>}
              </label>
            );
          })}
        </div>
      </fieldset>

      <Field label="Reason" error={validationError && !reasonCode ? validationError : undefined}>
        <select className={inputClass} value={reasonCode} onChange={(e) => setReasonCode(e.target.value)}>
          <option value="">Select a reason…</option>
          {VINES_DISPOSITION_REASONS.map((r) => (
            <option key={r.code} value={r.code}>
              {r.label}
            </option>
          ))}
        </select>
      </Field>

      <Field label={`Note ${reasonCode === "other" ? "(required)" : "(optional)"}`}>
        <textarea className={`${inputClass} min-h-20`} rows={2} value={note} onChange={(e) => setNote(e.target.value)} />
      </Field>

      <fieldset className="grid grid-cols-2 gap-3">
        <Field label="Date">
          <input type="date" className={inputClass} value={effectiveDate} onChange={(e) => setEffectiveDate(e.target.value)} />
        </Field>
        <Field label="Time">
          <input
            type="time" className={inputClass} value={effectiveTimeOfDay}
            onChange={(e) => setEffectiveTimeOfDay(e.target.value)}
          />
        </Field>
      </fieldset>

      {validationError && (
        <p role="alert" className={errorClass}>
          {validationError}
        </p>
      )}
      {serverError && (
        <p role="alert" className={errorClass}>
          {friendlyMutationErrorMessage(serverError)}
        </p>
      )}

      <div>
        <Button type="button" variant="primary" onClick={goToReview}>
          Review
        </Button>
      </div>
    </div>
  );
}
