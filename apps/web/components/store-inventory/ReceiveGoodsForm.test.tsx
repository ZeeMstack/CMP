/** PILOT-BLOCKER-008 A8: `ReceiveGoodsForm`'s "Received date"/"Received
 * time" fields must default to the operator's LOCAL wall-clock now, never
 * a UTC slice re-displayed as if it were local (the previous bug). */
import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { withQueryClient } from "@/lib/test-utils";

import { ReceiveGoodsForm } from "./ReceiveGoodsForm";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

describe("ReceiveGoodsForm", () => {
  const originalTz = process.env.TZ;

  beforeEach(() => {
    process.env.TZ = "America/New_York";
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse([])));
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
    process.env.TZ = originalTz;
  });

  it("defaults Received date/time to LOCAL now, not a UTC slice re-displayed as local", async () => {
    // 2026-03-02T02:30 UTC == 2026-03-01T21:30 America/New_York -- the old
    // `toISOString().slice(...)` bug would show 2026-03-02 / 02:30 instead.
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-03-02T02:30:00.000Z"));

    render(withQueryClient(<ReceiveGoodsForm onSubmit={vi.fn()} isSubmitting={false} />));

    const dateInput = screen.getByLabelText(/received date/i);
    const timeInput = screen.getByLabelText(/received time/i);
    expect(dateInput).toHaveValue("2026-03-01");
    expect(timeInput).toHaveValue("21:30");
  });
});
