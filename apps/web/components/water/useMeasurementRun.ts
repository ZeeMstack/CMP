"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import type { WaterMeasurementCreate, WaterMeasurementRead } from "@/lib/api/client";
import { toCommandError } from "@/lib/commands/frozenSubmission";
import type { AppError } from "@/lib/errors/adapter";

/** UX-OPS-001D: a multi-metric Measurement worksheet is N INDEPENDENT
 * `WaterMeasurement` commands, never one aggregate. On Confirm each filled
 * row gets its own frozen payload + `client_command_id`; rows are sent one
 * at a time in a fixed order; the run stops at the first failure; a
 * confirmed row is never sent again; an uncertain row is retried
 * byte-for-byte and only then do the still-unsent rows continue. Same
 * semantics as `useFrozenSubmission`, per row. */

export type MeasurementRowStatus = "not_sent" | "submitting" | "confirmed" | "uncertain" | "rejected";

export interface MeasurementRunRow {
  metric: string;
  label: string;
  instrumentLabel: string | null;
  /** Frozen wire payload -- sent as-is on first send and on every Retry. */
  payload: WaterMeasurementCreate;
  status: MeasurementRowStatus;
  result?: WaterMeasurementRead;
  error?: AppError;
}

export interface MeasurementRun {
  samplingPointId: string;
  samplingPointLabel: string;
  /** `null` = Now (server time); otherwise the one explicit instant frozen
   * into every row. */
  effectiveAt: string | null;
  notes: string | null;
  rows: MeasurementRunRow[];
}

export interface MeasurementDraftRow {
  metric: string;
  label: string;
  unit: string;
  value: string;
  instrumentId: string | null;
  instrumentLabel: string | null;
}

/** Freezes a Review draft into a run: blank rows are omitted (never sent as
 * zero/empty), and each selected row gets its own command id. */
export function buildMeasurementRun(
  draft: {
    samplingPointId: string;
    samplingPointLabel: string;
    effectiveAt: string | null;
    notes: string | null;
    rows: MeasurementDraftRow[];
  },
  mintId: () => string = () => crypto.randomUUID(),
): MeasurementRun {
  return {
    samplingPointId: draft.samplingPointId,
    samplingPointLabel: draft.samplingPointLabel,
    effectiveAt: draft.effectiveAt,
    notes: draft.notes,
    rows: draft.rows
      .filter((row) => row.value.trim() !== "")
      .map((row) => ({
        metric: row.metric,
        label: row.label,
        instrumentLabel: row.instrumentLabel,
        status: "not_sent" as const,
        payload: {
          metric: row.metric,
          value: row.value.trim(),
          unit: row.unit,
          effective_at: draft.effectiveAt,
          water_instrument_id: row.instrumentId,
          notes: draft.notes,
          client_command_id: mintId(),
        },
      })),
  };
}

export type MeasurementRunPhase = "running" | "uncertain" | "rejected" | "complete";

export function measurementRunPhase(run: MeasurementRun): MeasurementRunPhase {
  if (run.rows.some((r) => r.status === "uncertain")) return "uncertain";
  if (run.rows.some((r) => r.status === "rejected")) return "rejected";
  if (run.rows.every((r) => r.status === "confirmed")) return "complete";
  return "running";
}

function isUncertain(error: AppError): boolean {
  return error.kind === "network_error" || error.kind === "server_error";
}

export function useMeasurementRun(
  send: (samplingPointId: string, payload: WaterMeasurementCreate) => Promise<WaterMeasurementRead>,
) {
  const [run, setRun] = useState<MeasurementRun | null>(null);
  // The authoritative run for the async driver (state is for rendering).
  const runRef = useRef<MeasurementRun | null>(null);
  const sendRef = useRef(send);
  useEffect(() => {
    sendRef.current = send;
  });

  const commit = useCallback((next: MeasurementRun | null) => {
    runRef.current = next;
    setRun(next);
  }, []);

  const patchRow = useCallback(
    (owner: MeasurementRun, index: number, patch: Partial<MeasurementRunRow>): MeasurementRun | null => {
      const current = runRef.current;
      // A run that was cleared/replaced meanwhile is never written to.
      if (!current || current.samplingPointId !== owner.samplingPointId || current.rows[index]?.payload !== owner.rows[index]?.payload) {
        return null;
      }
      const next = { ...current, rows: current.rows.map((r, i) => (i === index ? { ...r, ...patch } : r)) };
      commit(next);
      return next;
    },
    [commit],
  );

  const sendRow = useCallback(
    async (owner: MeasurementRun, index: number): Promise<boolean> => {
      if (!patchRow(owner, index, { status: "submitting", error: undefined })) return false;
      const row = owner.rows[index];
      try {
        const result = await sendRef.current(owner.samplingPointId, row.payload);
        return Boolean(patchRow(owner, index, { status: "confirmed", result }));
      } catch (raw) {
        const error = toCommandError(raw);
        patchRow(owner, index, { status: isUncertain(error) ? "uncertain" : "rejected", error });
        return false;
      }
    },
    [patchRow],
  );

  /** Sends every still-unsent row in order, stopping at the first failure. */
  const drive = useCallback(async () => {
    for (;;) {
      const current = runRef.current;
      if (!current) return;
      const index = current.rows.findIndex((r) => r.status === "not_sent");
      if (index < 0) return;
      if (!(await sendRow(current, index))) return;
    }
  }, [sendRow]);

  const start = useCallback(
    (next: MeasurementRun) => {
      if (runRef.current && measurementRunPhase(runRef.current) !== "complete" && measurementRunPhase(runRef.current) !== "rejected") {
        return; // never replace an in-flight/unresolved run
      }
      commit(next);
      void drive();
    },
    [commit, drive],
  );

  /** Resends the uncertain row's exact frozen payload; on confirmation the
   * remaining unsent rows continue. */
  const retry = useCallback(async () => {
    const current = runRef.current;
    if (!current) return;
    const index = current.rows.findIndex((r) => r.status === "uncertain");
    if (index < 0) return;
    if (await sendRow(current, index)) await drive();
  }, [drive, sendRow]);

  /** Only for a complete or definitively-rejected run -- an uncertain or
   * running run can never be discarded. */
  const clear = useCallback(() => {
    const current = runRef.current;
    if (current && measurementRunPhase(current) !== "complete" && measurementRunPhase(current) !== "rejected") return;
    commit(null);
  }, [commit]);

  const phase = run ? measurementRunPhase(run) : null;
  return {
    run,
    phase,
    locked: phase === "running" || phase === "uncertain",
    start,
    retry,
    clear,
  };
}
