"use client";

import { useCallback, useRef, useState } from "react";

import { AppError } from "@/lib/errors/adapter";

export type QualityActionKind = "ORDINARY" | "PARTIAL" | "CORRECT" | "PARTIAL_CORRECT";

/** What happened to the most recently submitted attempt of the open
 * command -- drives which controls the panel shows. `"editing"` covers
 * both "nothing submitted yet" and "a definitive validation failure was
 * shown and the operator may edit and resubmit" (PILOT-BLOCKER-005 F05). */
export type QualityCommandOutcome = "editing" | "submitting" | "uncertain" | "conflict";

/** The only two backend `AppError.code` values that mean "your captured
 * correction target is no longer actionable" (`app/api/inventory_quality.py`'s
 * `_STALE_TARGET_CODES`) -- every other Quality 409 is a different, ordinary
 * definitive rejection and must never be classified as this kind of
 * conflict (PILOT-BLOCKER-005 CTO correction, point 5). */
const QUALITY_STALE_TARGET_CODES = new Set(["QUALITY_CORRECTION_TARGET_STALE", "QUALITY_CORRECTION_NO_CURRENT_DECISION"]);

/** Captured once when a Quality action opens, from the work-queue row the
 * operator was looking at at that moment. `targetEventId` is `null` for
 * ORDINARY/PARTIAL (no target) and the frozen event id for CORRECT/
 * PARTIAL_CORRECT -- a later queue refetch must never silently replace it
 * (F06: correction-target freeze). */
export interface QualityCommandContext {
  cohortId: string;
  kind: QualityActionKind;
  targetEventId: string | null;
  observedState: string;
  /** ORDINARY only -- which disposition button was clicked to open this
   * action (Release/Hold/Reject/Hold Release). */
  disposition?: string;
}

/** PILOT-BLOCKER-005 F05/F06: one small local Quality command-draft
 * primitive -- deliberately not a general command framework. It exists
 * only to (a) freeze a correction's target/context the moment its action
 * opens so a later queue refetch cannot silently retarget it, and (b) keep
 * one `client_command_id` and the exact submitted payload alive across an
 * uncertain-result Retry instead of minting a fresh id on every click. */
export function useQualityCommandDraft() {
  const [context, setContext] = useState<QualityCommandContext | null>(null);
  const [outcome, setOutcome] = useState<QualityCommandOutcome>("editing");
  const [error, setError] = useState<AppError | null>(null);
  const clientCommandIdRef = useRef<string | null>(null);
  const frozenPayloadRef = useRef<Record<string, unknown> | null>(null);

  const open = useCallback((ctx: QualityCommandContext) => {
    setContext(ctx);
    setOutcome("editing");
    setError(null);
    clientCommandIdRef.current = null;
    frozenPayloadRef.current = null;
  }, []);

  const close = useCallback(() => {
    setContext(null);
    setOutcome("editing");
    setError(null);
    clientCommandIdRef.current = null;
    frozenPayloadRef.current = null;
  }, []);

  /** Freezes and returns the exact payload for a fresh Confirm submission
   * (never for a Retry -- use `retry()` for that). Reuses the existing
   * `client_command_id` unless this is genuinely a new logical command:
   * the very first submit, or the draft values changed since the last
   * (definitively failed) attempt -- a bare Retry click never reaches this
   * function, so it never mints a new id merely because the operator
   * pressed Retry (F05). */
  const submit = useCallback((draftValues: Record<string, unknown>): Record<string, unknown> => {
    const previous = frozenPayloadRef.current;
    const previousValues = previous ? { ...previous, client_command_id: undefined } : null;
    const unchanged = previousValues !== null && JSON.stringify(previousValues) === JSON.stringify(draftValues);
    const clientCommandId = clientCommandIdRef.current && unchanged ? clientCommandIdRef.current : crypto.randomUUID();
    const payload = { ...draftValues, client_command_id: clientCommandId };
    clientCommandIdRef.current = clientCommandId;
    frozenPayloadRef.current = payload;
    setOutcome("submitting");
    setError(null);
    return payload;
  }, []);

  /** Resends the byte-for-byte frozen payload from the last attempt --
   * never re-derives it from current draft values. Returns `null` if there
   * is nothing to retry (should not happen once a command has been
   * submitted at least once). */
  const retry = useCallback((): Record<string, unknown> | null => {
    if (!frozenPayloadRef.current) return null;
    setOutcome("submitting");
    setError(null);
    return frozenPayloadRef.current;
  }, []);

  const handleSuccess = useCallback(() => {
    close();
  }, [close]);

  /** Classifies the failed attempt into the three outcome buckets the
   * ticket distinguishes: transport-uncertain, stale-target conflict, or
   * definitive validation failure.
   *
   * A 409 alone is NOT enough to mean "stale target" -- Quality has
   * several distinct 409s (segregation-of-duty, a reused
   * `client_command_id` with a different payload, partial-quantity
   * over-allocation) that are ordinary definitive rejections, not "the
   * correction's target changed since you opened this action". Only the
   * backend's own stable `code` (mirroring the existing
   * `HARVEST_CORRECTION_STALE` convention -- see `_STALE_TARGET_CODES` in
   * app/api/inventory_quality.py) identifies the latter; every other 409
   * -- code absent -- falls through to "editing" like any other definitive
   * failure, never auto-classified as a must-reopen conflict. */
  const handleError = useCallback((err: AppError) => {
    if (err.kind === "conflict" && QUALITY_STALE_TARGET_CODES.has(err.code ?? "")) {
      setOutcome("conflict");
    } else if (err.kind === "network_error" || err.kind === "server_error") {
      setOutcome("uncertain");
    } else {
      setOutcome("editing");
    }
    setError(err);
  }, []);

  return {
    context, outcome, error, isOpen: context !== null,
    open, close, submit, retry, handleSuccess, handleError,
  };
}
