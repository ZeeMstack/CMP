"use client";

import { useState } from "react";

import { Button } from "@/components/ui/Button";
import type { QualityWorkQueueRowRead } from "@/lib/api/client";
import { AppError } from "@/lib/errors/adapter";

const inputClass =
  "min-h-10 w-full rounded-md border border-wl-border bg-wl-surface px-3 text-sm text-wl-text focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-wl-focus";
const labelClass = "block text-xs font-medium text-wl-text-secondary";

const DISPOSITION_LABELS: Record<string, string> = {
  RELEASED: "Release", HELD: "Hold", REJECTED: "Reject", HOLD_RELEASED: "Hold Release",
};

const ALL_DISPOSITIONS = ["RELEASED", "HELD", "REJECTED", "HOLD_RELEASED"];

export type ActionKind = "ORDINARY" | "PARTIAL" | "CORRECT" | "PARTIAL_CORRECT";

/** Shows the backend's error text verbatim for a domain conflict/invalid
 * request (segregation-of-duty rejections, invalid transitions) --
 * these carry specific, actionable wording that a generic message would
 * throw away (docs/build-plans/
 * STORE_INV_002A2_QUALITY_OPERATIONAL_UX_BUILD_PLAN.md, "Quality" section:
 * segregation rejections must never read as a generic permission-denied
 * message). */
function errorMessage(error: AppError): string {
  if (error.kind === "conflict" || error.kind === "invalid_request") return error.message;
  if (error.kind === "permission_error") return "You don't have permission to perform this action.";
  return "Something went wrong. Please try again.";
}

function nowLocalDateTime(): string {
  const now = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}T${pad(now.getHours())}:${pad(now.getMinutes())}`;
}

export function QualityActionPanel({
  row, kind, disposition, legalReplacements, onCancel, onSubmitOrdinary, onSubmitPartial, onSubmitCorrect,
  onSubmitPartialCorrect, isSubmitting, serverError,
}: {
  row: QualityWorkQueueRowRead;
  kind: ActionKind;
  disposition?: string;
  legalReplacements?: string[];
  onCancel: () => void;
  onSubmitOrdinary?: (args: { reason: string; effectiveTime: string }) => void;
  onSubmitPartial?: (args: { quantity: string; disposition: string; reason: string; effectiveTime: string }) => void;
  onSubmitCorrect?: (args: { reason: string; replacementDisposition: string | null; effectiveTime: string }) => void;
  onSubmitPartialCorrect?: (
    args: { quantity: string; correctedDisposition: string; reason: string; effectiveTime: string },
  ) => void;
  isSubmitting: boolean;
  serverError?: AppError | null;
}) {
  const [reason, setReason] = useState("");
  const [effectiveTime, setEffectiveTime] = useState(() => nowLocalDateTime());
  const [quantity, setQuantity] = useState("");
  const [partialDisposition, setPartialDisposition] = useState(legalReplacements?.[0] ?? "");
  const [replacementDisposition, setReplacementDisposition] = useState("");
  const [correctedDisposition, setCorrectedDisposition] = useState(ALL_DISPOSITIONS[0]);

  const title =
    kind === "ORDINARY" ? DISPOSITION_LABELS[disposition ?? ""] ?? disposition
    : kind === "PARTIAL" ? "Apply disposition to part of quantity"
    : kind === "PARTIAL_CORRECT" ? "Correct decision for part of quantity"
    : "Correct decision";

  return (
    <div className="flex flex-col gap-3 rounded-lg border border-wl-border bg-wl-surface p-3">
      <h4 className="text-sm font-semibold text-wl-text">{title}</h4>

      {kind === "PARTIAL" && (
        <>
          <label className="flex flex-col gap-1">
            <span className={labelClass}>Quantity (of {row.balance} currently {row.current_state})</span>
            <input
              className={inputClass}
              type="number"
              min="0"
              step="any"
              value={quantity}
              onChange={(e) => setQuantity(e.target.value)}
            />
          </label>
          <label className="flex flex-col gap-1">
            <span className={labelClass}>New disposition</span>
            <select className={inputClass} value={partialDisposition} onChange={(e) => setPartialDisposition(e.target.value)}>
              {(legalReplacements ?? []).map((d) => (
                <option key={d} value={d}>{DISPOSITION_LABELS[d] ?? d}</option>
              ))}
            </select>
          </label>
        </>
      )}

      {kind === "CORRECT" && (
        <label className="flex flex-col gap-1">
          <span className={labelClass}>Replacement decision (optional)</span>
          <select className={inputClass} value={replacementDisposition} onChange={(e) => setReplacementDisposition(e.target.value)}>
            <option value="">No replacement — revert to prior decision</option>
            {(legalReplacements ?? []).map((d) => (
              <option key={d} value={d}>{DISPOSITION_LABELS[d] ?? d}</option>
            ))}
          </select>
        </label>
      )}

      {kind === "PARTIAL_CORRECT" && (
        <>
          <p className="text-xs text-wl-text-tertiary">
            This corrects a mistaken classification for part of the quantity -- not an ordinary transition. The
            remaining quantity keeps its current {row.current_state} decision untouched.
          </p>
          <label className="flex flex-col gap-1">
            <span className={labelClass}>Quantity (of {row.balance} currently {row.current_state})</span>
            <input
              className={inputClass}
              type="number"
              min="0"
              step="any"
              value={quantity}
              onChange={(e) => setQuantity(e.target.value)}
            />
          </label>
          <label className="flex flex-col gap-1">
            <span className={labelClass}>Corrected decision</span>
            <select className={inputClass} value={correctedDisposition} onChange={(e) => setCorrectedDisposition(e.target.value)}>
              {ALL_DISPOSITIONS.map((d) => (
                <option key={d} value={d}>{DISPOSITION_LABELS[d] ?? d}</option>
              ))}
            </select>
          </label>
        </>
      )}

      <label className="flex flex-col gap-1">
        <span className={labelClass}>Effective time</span>
        <input className={inputClass} type="datetime-local" value={effectiveTime} onChange={(e) => setEffectiveTime(e.target.value)} />
      </label>

      <label className="flex flex-col gap-1">
        <span className={labelClass}>
          {kind === "CORRECT" || kind === "PARTIAL_CORRECT" ? "Reason (required)" : "Reason (optional)"}
        </span>
        <input className={inputClass} value={reason} onChange={(e) => setReason(e.target.value)} />
      </label>

      {serverError && (
        <p className="rounded-md border border-red-300 bg-red-50 p-2 text-xs text-red-800">
          {errorMessage(serverError)}
        </p>
      )}

      <div className="flex gap-2">
        <Button
          type="button"
          variant="primary"
          disabled={
            isSubmitting ||
            (kind === "PARTIAL" && (!quantity || Number(quantity) <= 0 || !partialDisposition)) ||
            (kind === "CORRECT" && !reason.trim()) ||
            (kind === "PARTIAL_CORRECT" && (!quantity || Number(quantity) <= 0 || !reason.trim()))
          }
          onClick={() => {
            const iso = new Date(effectiveTime).toISOString();
            if (kind === "ORDINARY") onSubmitOrdinary?.({ reason, effectiveTime: iso });
            if (kind === "PARTIAL") onSubmitPartial?.({ quantity, disposition: partialDisposition, reason, effectiveTime: iso });
            if (kind === "CORRECT") {
              onSubmitCorrect?.({
                reason, replacementDisposition: replacementDisposition || null, effectiveTime: iso,
              });
            }
            if (kind === "PARTIAL_CORRECT") {
              onSubmitPartialCorrect?.({ quantity, correctedDisposition, reason, effectiveTime: iso });
            }
          }}
        >
          {isSubmitting ? "Submitting…" : "Confirm"}
        </Button>
        <Button type="button" variant="secondary" onClick={onCancel} disabled={isSubmitting}>
          Cancel
        </Button>
      </div>
    </div>
  );
}
