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

/** Returned by `submit()`/`retry()`: the frozen wire payload plus the
 * command-slot generation it belongs to (PILOT-BLOCKER-008 A2) -- callers
 * must pass `generation` straight through to `handleSuccess`/`handleError`
 * unchanged. */
export interface SubmittedCommand {
  payload: Record<string, unknown>;
  generation: number;
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
  // PILOT-BLOCKER-008 A2: mirrors `outcome` for synchronous reads inside
  // stable callbacks (`close`) that must never act on a stale closed-over
  // value.
  const outcomeRef = useRef<QualityCommandOutcome>("editing");
  const setOutcomeTracked = useCallback((next: QualityCommandOutcome) => {
    outcomeRef.current = next;
    setOutcome(next);
  }, []);
  // PILOT-BLOCKER-008 A2: identifies which open command "slot" a submitted
  // attempt belongs to. Bumped whenever the draft opens or closes, so a late
  // response belonging to a command whose slot has since moved on (e.g. the
  // operator closed this draft and opened a different one) can never mutate
  // a newer draft's outcome/error state -- `handleSuccess`/`handleError`
  // check the generation they were given against this before applying
  // anything.
  const generationRef = useRef(0);

  const open = useCallback((ctx: QualityCommandContext) => {
    generationRef.current += 1;
    setContext(ctx);
    setOutcomeTracked("editing");
    setError(null);
    clientCommandIdRef.current = null;
    frozenPayloadRef.current = null;
  }, [setOutcomeTracked]);

  const close = useCallback(() => {
    // PILOT-BLOCKER-008 A2: once a submitted command's outcome is
    // uncertain, its frozen id/payload must remain recoverable until
    // resolved -- an ordinary Cancel/Close must not silently discard it.
    // (The Cancel button itself is also disabled during "uncertain" in
    // `QualityActionPanel`; this is defense in depth against any other
    // path that might call `close()` directly.)
    if (outcomeRef.current === "uncertain") return;
    generationRef.current += 1;
    setContext(null);
    setOutcomeTracked("editing");
    setError(null);
    clientCommandIdRef.current = null;
    frozenPayloadRef.current = null;
  }, [setOutcomeTracked]);

  /** Freezes and returns the exact payload for a fresh Confirm submission
   * (never for a Retry -- use `retry()` for that). Reuses the existing
   * `client_command_id` unless this is genuinely a new logical command:
   * the very first submit, or the draft values changed since the last
   * (definitively failed) attempt -- a bare Retry click never reaches this
   * function, so it never mints a new id merely because the operator
   * pressed Retry (F05). */
  const submit = useCallback((draftValues: Record<string, unknown>): SubmittedCommand => {
    const previous = frozenPayloadRef.current;
    const previousValues = previous ? { ...previous, client_command_id: undefined } : null;
    const unchanged = previousValues !== null && JSON.stringify(previousValues) === JSON.stringify(draftValues);
    const clientCommandId = clientCommandIdRef.current && unchanged ? clientCommandIdRef.current : crypto.randomUUID();
    const payload = { ...draftValues, client_command_id: clientCommandId };
    clientCommandIdRef.current = clientCommandId;
    frozenPayloadRef.current = payload;
    setOutcomeTracked("submitting");
    setError(null);
    return { payload, generation: generationRef.current };
  }, [setOutcomeTracked]);

  /** Resends the byte-for-byte frozen payload from the last attempt --
   * never re-derives it from current draft values. Returns `null` if there
   * is nothing to retry (should not happen once a command has been
   * submitted at least once). */
  const retry = useCallback((): SubmittedCommand | null => {
    if (!frozenPayloadRef.current) return null;
    setOutcomeTracked("submitting");
    setError(null);
    return { payload: frozenPayloadRef.current, generation: generationRef.current };
  }, [setOutcomeTracked]);

  /** `generation` must be the value captured from the `submit()`/`retry()`
   * call this response belongs to (PILOT-BLOCKER-008 A2) -- if the draft has
   * since moved on to a different command slot (closed and reopened), this
   * is a no-op: a late response from an abandoned command must never mutate
   * a newer draft's state. */
  const handleSuccess = useCallback((generation: number) => {
    if (generation !== generationRef.current) return;
    close();
  }, [close]);

  /** Classifies the failed attempt into the three outcome buckets the
   * ticket distinguishes: transport-uncertain, stale-target conflict, or
   * definitive validation failure. `generation` guards against a late
   * response mutating a newer draft, exactly as in `handleSuccess`.
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
  const handleError = useCallback((err: AppError, generation: number) => {
    if (generation !== generationRef.current) return;
    if (err.kind === "conflict" && QUALITY_STALE_TARGET_CODES.has(err.code ?? "")) {
      setOutcomeTracked("conflict");
    } else if (err.kind === "network_error" || err.kind === "server_error") {
      setOutcomeTracked("uncertain");
    } else {
      setOutcomeTracked("editing");
    }
    setError(err);
  }, [setOutcomeTracked]);

  return {
    context, outcome, error, isOpen: context !== null,
    open, close, submit, retry, handleSuccess, handleError,
  };
}
