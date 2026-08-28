"use client";

import { useState } from "react";

import { Button } from "@/components/ui/Button";

const inputClass =
  "min-h-11 w-full rounded-md border border-border-subtle bg-surface px-3 text-sm text-ink focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-600";
const labelClass = "block text-sm font-medium text-ink";
const errorClass = "text-xs text-red-700";

/** POSTHARVEST-OPS-001H: the mandatory-reason confirmation for a whole-event
 * Grading/Packing reversal -- never a field-by-field correction. Reason is
 * required; note is optional (PRE-COMMIT AUDIT: mirrors
 * `SeedlingDispositionEvent`'s own REVERSAL shape, this codebase's closest
 * existing "whole-event reversal" precedent -- not
 * `HarvestSourceLineCorrection`'s stricter both-mandatory field-correction
 * shape). No "replace with corrected facts" mode (the operator re-enters the
 * correct transaction afterward through the normal Grading/Packing
 * workflow). Shared between `GradingHistoryPanel` and `PackingHistoryPanel`. */
export function ReversalConfirmForm({
  title, description, onConfirm, onCancel, isSubmitting, serverError,
}: {
  title: string;
  description: string;
  onConfirm: (payload: { reason_code: string; note: string | null }) => void;
  onCancel: () => void;
  isSubmitting: boolean;
  serverError?: string | null;
}) {
  const [reasonCode, setReasonCode] = useState("");
  const [note, setNote] = useState("");
  const [touched, setTouched] = useState(false);

  const reasonError = touched && !reasonCode.trim() ? "A reason is required." : null;

  function submit(e: React.FormEvent) {
    e.preventDefault();
    setTouched(true);
    if (!reasonCode.trim()) return;
    onConfirm({ reason_code: reasonCode.trim(), note: note.trim() || null });
  }

  return (
    <form
      onSubmit={submit}
      className="flex flex-col gap-3 rounded-xl border border-red-200 bg-red-50 p-4"
    >
      <div>
        <h4 className="text-sm font-semibold text-ink">{title}</h4>
        <p className="text-sm text-ink-muted">{description}</p>
      </div>

      <label className="flex flex-col gap-1">
        <span className={labelClass}>Reason</span>
        <input
          type="text"
          value={reasonCode}
          onChange={(e) => setReasonCode(e.target.value)}
          placeholder="e.g. OPERATOR_ERROR"
          className={inputClass}
        />
        {reasonError && <span className={errorClass}>{reasonError}</span>}
      </label>

      <label className="flex flex-col gap-1">
        <span className={labelClass}>Note (optional)</span>
        <textarea
          value={note}
          onChange={(e) => setNote(e.target.value)}
          rows={2}
          className={`${inputClass} min-h-20`}
        />
      </label>

      {serverError && <p role="alert" className={errorClass}>{serverError}</p>}

      <div className="flex gap-3">
        <Button type="button" variant="secondary" onClick={onCancel} disabled={isSubmitting}>
          Cancel
        </Button>
        <Button type="submit" variant="danger" disabled={isSubmitting}>
          {isSubmitting ? "Reversing…" : "Confirm reversal"}
        </Button>
      </div>
    </form>
  );
}
