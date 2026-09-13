"use client";

import { useState } from "react";

import { Button } from "@/components/ui/Button";
import type { QualityWorkQueueRowRead, StorageBucketRead } from "@/lib/api/client";
import { nowLocalDateTime } from "@/lib/datetime";
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

/** STORE-INV-002B: sentinel value for the "Not put away" bucket option --
 * the actual command payload maps this back to `null` (`custody_location_id`
 * is the not-put-away bucket when absent), never an empty string, since an
 * empty string is indistinguishable from "no selection yet" in a <select>. */
const NOT_PUT_AWAY_BUCKET_VALUE = "__not_put_away__";

export function QualityActionPanel({
  row, kind, disposition, legalReplacements, buckets, onCancel, onSubmitOrdinary, onSubmitPartial, onSubmitCorrect,
  onSubmitPartialCorrect, isSubmitting, serverError, commandOutcome, onRetry, bucketsError, onRetryBuckets,
}: {
  row: QualityWorkQueueRowRead;
  kind: ActionKind;
  disposition?: string;
  legalReplacements?: string[];
  /** STORE-INV-002B: every eligible physical bucket for a PARTIAL/
   * PARTIAL_CORRECT action -- "Not put away" (`location_id: null`) plus
   * one row per Bin with a positive balance. Auto-selected when there is
   * exactly one; shown as a dropdown otherwise. Omitted/empty is treated
   * as "Not put away only" (defensive default, never blocks submission)
   * UNLESS `bucketsError` is set (F08) -- a failed bucket fetch is never
   * silently presented as "no buckets exist". */
  buckets?: StorageBucketRead[];
  onCancel: () => void;
  onSubmitOrdinary?: (args: { reason: string; effectiveTime: string }) => void;
  onSubmitPartial?: (
    args: { quantity: string; disposition: string; reason: string; effectiveTime: string; custodyLocationId: string | null },
  ) => void;
  onSubmitCorrect?: (args: { reason: string; replacementDisposition: string | null; effectiveTime: string }) => void;
  onSubmitPartialCorrect?: (
    args: {
      quantity: string; correctedDisposition: string; reason: string; effectiveTime: string;
      custodyLocationId: string | null;
    },
  ) => void;
  isSubmitting: boolean;
  serverError?: AppError | null;
  /** PILOT-BLOCKER-005 F05/F06: which outcome the open command-draft is
   * currently in -- `"uncertain"` (transport failure/timeout) offers Retry
   * instead of Confirm and freezes the fields; `"conflict"` (stale target/
   * superseded Quality state) offers only Close, never a silent retarget. */
  commandOutcome?: "editing" | "submitting" | "uncertain" | "conflict";
  onRetry?: () => void;
  /** F08: the PARTIAL/PARTIAL_CORRECT bucket-breakdown query failed -- an
   * empty bucket list is never presented as authoritative in this case. */
  bucketsError?: AppError | null;
  onRetryBuckets?: () => void;
}) {
  const [reason, setReason] = useState("");
  const [effectiveTime, setEffectiveTime] = useState(() => nowLocalDateTime());
  const [quantity, setQuantity] = useState("");
  const [partialDisposition, setPartialDisposition] = useState(legalReplacements?.[0] ?? "");
  const [replacementDisposition, setReplacementDisposition] = useState("");
  const [correctedDisposition, setCorrectedDisposition] = useState(ALL_DISPOSITIONS[0]);
  const bucketOptions = buckets ?? [];
  const [bucketValue, setBucketValue] = useState(
    () => bucketOptions[0]?.location_id ?? NOT_PUT_AWAY_BUCKET_VALUE,
  );
  const resolvedCustodyLocationId = bucketValue === NOT_PUT_AWAY_BUCKET_VALUE ? null : bucketValue;

  const title =
    kind === "ORDINARY" ? DISPOSITION_LABELS[disposition ?? ""] ?? disposition
    : kind === "PARTIAL" ? "Apply disposition to part of quantity"
    : kind === "PARTIAL_CORRECT" ? "Correct decision for part of quantity"
    : "Correct decision";

  const fieldsDisabled = isSubmitting || commandOutcome === "uncertain" || commandOutcome === "conflict";
  const showBucketsError = (kind === "PARTIAL" || kind === "PARTIAL_CORRECT") && Boolean(bucketsError);

  return (
    <div className="flex flex-col gap-3 rounded-lg border border-wl-border bg-wl-surface p-3">
      <h4 className="text-sm font-semibold text-wl-text">{title}</h4>

      {showBucketsError && (
        <p className="flex flex-wrap items-center gap-2 rounded-md border border-wl-border-strong bg-wl-flag-bg p-2 text-xs text-wl-flag-fg">
          Could not load this cohort&apos;s storage locations -- the affected location cannot be confirmed yet.
          {onRetryBuckets && (
            <button type="button" className="font-medium underline" onClick={onRetryBuckets}>
              Retry
            </button>
          )}
        </p>
      )}

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
              disabled={fieldsDisabled}
            />
          </label>
          {bucketOptions.length > 1 && (
            <label className="flex flex-col gap-1">
              <span className={labelClass}>Affected location</span>
              <select
                className={inputClass} value={bucketValue} onChange={(e) => setBucketValue(e.target.value)}
                disabled={fieldsDisabled}
              >
                {bucketOptions.map((b) => (
                  <option key={b.location_id ?? NOT_PUT_AWAY_BUCKET_VALUE} value={b.location_id ?? NOT_PUT_AWAY_BUCKET_VALUE}>
                    {b.label} ({b.balance})
                  </option>
                ))}
              </select>
            </label>
          )}
          <label className="flex flex-col gap-1">
            <span className={labelClass}>New disposition</span>
            <select
              className={inputClass} value={partialDisposition} onChange={(e) => setPartialDisposition(e.target.value)}
              disabled={fieldsDisabled}
            >
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
          <select
            className={inputClass} value={replacementDisposition} onChange={(e) => setReplacementDisposition(e.target.value)}
            disabled={fieldsDisabled}
          >
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
              disabled={fieldsDisabled}
            />
          </label>
          {bucketOptions.length > 1 && (
            <label className="flex flex-col gap-1">
              <span className={labelClass}>Affected location</span>
              <select
                className={inputClass} value={bucketValue} onChange={(e) => setBucketValue(e.target.value)}
                disabled={fieldsDisabled}
              >
                {bucketOptions.map((b) => (
                  <option key={b.location_id ?? NOT_PUT_AWAY_BUCKET_VALUE} value={b.location_id ?? NOT_PUT_AWAY_BUCKET_VALUE}>
                    {b.label} ({b.balance})
                  </option>
                ))}
              </select>
            </label>
          )}
          <label className="flex flex-col gap-1">
            <span className={labelClass}>Corrected decision</span>
            <select
              className={inputClass} value={correctedDisposition} onChange={(e) => setCorrectedDisposition(e.target.value)}
              disabled={fieldsDisabled}
            >
              {ALL_DISPOSITIONS.map((d) => (
                <option key={d} value={d}>{DISPOSITION_LABELS[d] ?? d}</option>
              ))}
            </select>
          </label>
        </>
      )}

      <label className="flex flex-col gap-1">
        <span className={labelClass}>Effective time</span>
        <input
          className={inputClass} type="datetime-local" value={effectiveTime}
          onChange={(e) => setEffectiveTime(e.target.value)} disabled={fieldsDisabled}
        />
      </label>

      <label className="flex flex-col gap-1">
        <span className={labelClass}>
          {kind === "CORRECT" || kind === "PARTIAL_CORRECT" ? "Reason (required)" : "Reason (optional)"}
        </span>
        <input className={inputClass} value={reason} onChange={(e) => setReason(e.target.value)} disabled={fieldsDisabled} />
      </label>

      {commandOutcome === "uncertain" && (
        <p className="rounded-md border border-amber-300 bg-amber-50 p-2 text-xs text-amber-900">
          Result not confirmed -- this command was submitted but the server&apos;s response was never received. Retry
          sends the exact same submitted values again; it is safe to press even if the original attempt actually
          went through.
        </p>
      )}
      {serverError && commandOutcome !== "uncertain" && (
        <p className="rounded-md border border-red-300 bg-red-50 p-2 text-xs text-red-800">
          {errorMessage(serverError)}
          {commandOutcome === "conflict" && " Close this action and open a new one to try again."}
        </p>
      )}

      <div className="flex gap-2">
        {commandOutcome === "conflict" ? (
          <Button type="button" variant="secondary" onClick={onCancel}>
            Close
          </Button>
        ) : commandOutcome === "uncertain" ? (
          <>
            <Button type="button" variant="primary" disabled={isSubmitting} onClick={onRetry}>
              {isSubmitting ? "Retrying…" : "Retry"}
            </Button>
            {/* PILOT-BLOCKER-008 A2: Cancel must stay disabled for the whole
                "uncertain" state, not just while a retry is in flight -- the
                frozen command must remain recoverable until its outcome is
                actually resolved (success, definitive rejection, or a
                confirmed reconciliation), never discardable via an ordinary
                Cancel click. */}
            <Button type="button" variant="secondary" onClick={onCancel} disabled>
              Cancel
            </Button>
          </>
        ) : (
          <>
            <Button
              type="button"
              variant="primary"
              disabled={
                isSubmitting ||
                showBucketsError ||
                (kind === "PARTIAL" && (!quantity || Number(quantity) <= 0 || !partialDisposition)) ||
                (kind === "CORRECT" && !reason.trim()) ||
                (kind === "PARTIAL_CORRECT" && (!quantity || Number(quantity) <= 0 || !reason.trim()))
              }
              onClick={() => {
                const iso = new Date(effectiveTime).toISOString();
                if (kind === "ORDINARY") onSubmitOrdinary?.({ reason, effectiveTime: iso });
                if (kind === "PARTIAL") {
                  onSubmitPartial?.({
                    quantity, disposition: partialDisposition, reason, effectiveTime: iso,
                    custodyLocationId: resolvedCustodyLocationId,
                  });
                }
                if (kind === "CORRECT") {
                  onSubmitCorrect?.({
                    reason, replacementDisposition: replacementDisposition || null, effectiveTime: iso,
                  });
                }
                if (kind === "PARTIAL_CORRECT") {
                  onSubmitPartialCorrect?.({
                    quantity, correctedDisposition, reason, effectiveTime: iso,
                    custodyLocationId: resolvedCustodyLocationId,
                  });
                }
              }}
            >
              {isSubmitting ? "Submitting…" : "Confirm"}
            </Button>
            <Button type="button" variant="secondary" onClick={onCancel} disabled={isSubmitting}>
              Cancel
            </Button>
          </>
        )}
      </div>
    </div>
  );
}
