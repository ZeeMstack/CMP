"use client";

import { useCallback, useRef, useState } from "react";

import { AppError } from "@/lib/errors/adapter";

/** `"editing"` covers both "nothing submitted yet" and "a definitive
 * rejection was shown and the operator may edit and resubmit". `"uncertain"`
 * means the request's outcome was never confirmed (network failure/timeout/
 * 5xx) -- the frozen command must stay recoverable until Retry (or an
 * authoritative refresh) resolves it, never silently discarded. */
export type FrozenSubmissionOutcome = "editing" | "submitting" | "uncertain";

/** PILOT-BLOCKER-008 A3/A5: a minimal frozen-command primitive for a single
 * fire-and-forget backend command whose backend already supports safe exact
 * replay by `(tenant_id, client_command_id)` (Putaway, Storage Transfer --
 * both already idempotent server-side via a request-fingerprint check).
 * Freezes `client_command_id` and the submitted payload across a submit;
 * keeps them frozen and byte-exact through an uncertain-outcome Retry
 * instead of minting a fresh id on every click; only allows a genuinely new
 * logical command (a fresh id) once a definitive rejection lets the
 * operator edit and resubmit.
 *
 * Deliberately not a general command framework: no retry backoff, no
 * queue, no conflict/stale-target concept (these commands don't have one --
 * see `useQualityCommandDraft` for that richer shape where Quality needs
 * it). Duplicated here rather than shared with Quality's hook because the
 * two outcome sets and semantics differ (Quality also has a `"conflict"`
 * outcome tied to a correction-target concept Putaway/Transfer don't have). */
export function useFrozenSubmission<TPayload extends Record<string, unknown>>() {
  const [outcome, setOutcome] = useState<FrozenSubmissionOutcome>("editing");
  const [error, setError] = useState<AppError | null>(null);
  // `clientCommandIdRef` is never read during render (only inside submit()'s
  // own logic), so a ref is fine for it; `frozenPayload` IS read during
  // render by callers (to display the frozen values while uncertain), so it
  // must be state -- reading a ref's `.current` during render is invalid
  // (react-hooks/refs) and would not reliably trigger a re-render anyway.
  const clientCommandIdRef = useRef<string | null>(null);
  const [frozenPayload, setFrozenPayload] = useState<TPayload | null>(null);

  /** `buildPayload` receives the (possibly reused) `client_command_id` to
   * fold into the wire payload it returns. */
  const submit = useCallback((buildPayload: (clientCommandId: string) => TPayload): TPayload => {
    const clientCommandId = clientCommandIdRef.current ?? crypto.randomUUID();
    const payload = buildPayload(clientCommandId);
    clientCommandIdRef.current = clientCommandId;
    setFrozenPayload(payload);
    setOutcome("submitting");
    setError(null);
    return payload;
  }, []);

  /** Resends the byte-for-byte frozen payload from the last attempt --
   * never re-derives it from current field values. `null` if there is
   * nothing to retry. */
  const retry = useCallback((): TPayload | null => {
    if (!frozenPayload) return null;
    setOutcome("submitting");
    setError(null);
    return frozenPayload;
  }, [frozenPayload]);

  const handleSuccess = useCallback(() => {
    setOutcome("editing");
    setError(null);
    clientCommandIdRef.current = null;
    setFrozenPayload(null);
  }, []);

  const handleError = useCallback((err: AppError) => {
    if (err.kind === "network_error" || err.kind === "server_error") {
      setOutcome("uncertain");
      // Deliberately keep clientCommandIdRef/frozenPayload intact -- the
      // whole point of "uncertain" is that this exact command must remain
      // retryable.
    } else {
      // Definitive rejection: the operator may edit and resubmit, which is
      // a genuinely new logical command -- clearing the frozen id/payload
      // here means the next submit() mints a fresh client_command_id.
      setOutcome("editing");
      clientCommandIdRef.current = null;
      setFrozenPayload(null);
    }
    setError(err);
  }, []);

  return {
    outcome, error,
    /** The exact payload from the last submit/retry, or `null` before the
     * first submission. Callers should render field DISPLAYS from this
     * (not live form state) whenever `outcome !== "editing"`, so a
     * background query refetch can never make the screen show values
     * different from what Retry will actually resend. */
    frozenPayload,
    submit, retry, handleSuccess, handleError,
  };
}
