import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { WaterMeasurementCreate } from "@/lib/api/client";
import { AppError } from "@/lib/errors/adapter";

import { buildMeasurementRun, useMeasurementRun } from "./useMeasurementRun";

const ROWS = [
  { metric: "PH", label: "pH", unit: "pH", value: "6.1", instrumentId: null, instrumentLabel: null },
  { metric: "EC", label: "EC", unit: "mS/cm", value: "", instrumentId: null, instrumentLabel: null },
  { metric: "SOLUTION_TEMPERATURE", label: "Temp", unit: "°C", value: "21.5", instrumentId: "inst-1", instrumentLabel: "M-1" },
  { metric: "DISSOLVED_OXYGEN", label: "DO", unit: "mg/L", value: "8", instrumentId: null, instrumentLabel: null },
];

function draft(effectiveAt: string | null = null) {
  return { samplingPointId: "sp-1", samplingPointLabel: "SP-1 — Tank A", effectiveAt, notes: "shared", rows: ROWS };
}

function result(payload: WaterMeasurementCreate, n: number) {
  return {
    id: `m-${n}`, tenant_id: "t", farm_id: "farm-1", sampling_point_id: "sp-1", metric: payload.metric,
    value: String(payload.value), unit: payload.unit, effective_at: `2026-09-24T08:00:0${n}Z`,
    recorded_at: "2026-09-24T08:00:00Z", water_instrument_id: payload.water_instrument_id ?? null, notes: payload.notes ?? null,
  };
}

describe("buildMeasurementRun", () => {
  it("omits blank rows and gives every selected row its own command id, in fixed metric order", () => {
    let n = 0;
    const run = buildMeasurementRun(draft(), () => `cmd-${++n}`);
    expect(run.rows.map((r) => r.metric)).toEqual(["PH", "SOLUTION_TEMPERATURE", "DISSOLVED_OXYGEN"]);
    expect(run.rows.map((r) => r.payload.client_command_id)).toEqual(["cmd-1", "cmd-2", "cmd-3"]);
    // Now = null on every row (server time); notes shared; instrument per row.
    expect(run.rows.every((r) => r.payload.effective_at === null && r.payload.notes === "shared")).toBe(true);
    expect(run.rows[1].payload.water_instrument_id).toBe("inst-1");
  });

  it("freezes one explicit custom instant into every selected row", () => {
    const run = buildMeasurementRun(draft("2026-09-24T06:30:00.000Z"));
    expect(new Set(run.rows.map((r) => r.payload.effective_at))).toEqual(new Set(["2026-09-24T06:30:00.000Z"]));
  });
});

describe("useMeasurementRun partial results", () => {
  it("stops at an uncertain row, retries it byte-for-byte, then sends only the still-unsent rows -- never a confirmed row", async () => {
    const sent: string[] = [];
    let call = 0;
    const send = vi.fn(async (_sp: string, payload: WaterMeasurementCreate) => {
      sent.push(JSON.stringify(payload));
      call += 1;
      if (call === 2) throw new AppError("network_error", "offline");
      return result(payload, call);
    });
    const { result: hook } = renderHook(() => useMeasurementRun(send));
    const run = buildMeasurementRun(draft());

    act(() => hook.current.start(run));
    await waitFor(() => expect(hook.current.phase).toBe("uncertain"));
    expect(hook.current.run?.rows.map((r) => r.status)).toEqual(["confirmed", "uncertain", "not_sent"]);
    expect(hook.current.locked).toBe(true);
    // An uncertain run can never be discarded.
    act(() => hook.current.clear());
    expect(hook.current.run).not.toBeNull();

    await act(async () => {
      await hook.current.retry();
    });
    await waitFor(() => expect(hook.current.phase).toBe("complete"));
    expect(sent).toHaveLength(4);
    expect(sent[2]).toBe(sent[1]); // byte-identical retry of the uncertain row
    expect(sent[3]).toBe(JSON.stringify(run.rows[2].payload)); // then only the unsent row
    expect(sent.filter((body) => body === JSON.stringify(run.rows[0].payload))).toHaveLength(1); // confirmed row sent once
    expect(hook.current.run?.rows.map((r) => r.result?.id)).toEqual(["m-1", "m-3", "m-4"]);
  });

  it("a definitive rejection stops the run, keeps confirmed rows confirmed, and leaves later rows unsent", async () => {
    let call = 0;
    const send = vi.fn(async (_sp: string, payload: WaterMeasurementCreate) => {
      call += 1;
      if (call === 2) throw new AppError("invalid_request", "value out of range", 422);
      return result(payload, call);
    });
    const { result: hook } = renderHook(() => useMeasurementRun(send));
    act(() => hook.current.start(buildMeasurementRun(draft())));
    await waitFor(() => expect(hook.current.phase).toBe("rejected"));
    expect(hook.current.run?.rows.map((r) => r.status)).toEqual(["confirmed", "rejected", "not_sent"]);
    expect(hook.current.locked).toBe(false);
    expect(send).toHaveBeenCalledTimes(2);
  });
});
