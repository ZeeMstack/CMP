/** PILOT-BLOCKER-008 A8: proves `nowLocalDate`/`nowLocalTime`/
 * `nowLocalDateTime` use LOCAL calendar/time getters, never a UTC slice --
 * the previous bug (`new Date().toISOString().slice(...)`) is only visible
 * under a system clock whose UTC and local calendar date/hour actually
 * differ, so this test forces a non-UTC `TZ` explicitly rather than relying
 * on whatever zone the CI machine happens to run in. */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { nowLocalDate, nowLocalDateTime, nowLocalTime } from "@/lib/datetime";

describe("datetime local helpers", () => {
  const originalTz = process.env.TZ;

  beforeEach(() => {
    // America/New_York: UTC-4/UTC-5 depending on DST -- guarantees a real
    // divergence from the fixed UTC instant below, regardless of the
    // machine running this suite.
    process.env.TZ = "America/New_York";
  });

  afterEach(() => {
    vi.useRealTimers();
    process.env.TZ = originalTz;
  });

  it("uses the LOCAL calendar date/time, not a UTC slice, across a UTC day boundary", () => {
    // 2026-03-02T02:30:00 UTC == 2026-03-01T21:30 America/New_York (still
    // the PREVIOUS calendar day, and a different hour, in local time) --
    // the exact scenario the old `toISOString().slice(...)` bug got wrong.
    const fixedInstant = new Date("2026-03-02T02:30:00.000Z");
    vi.useFakeTimers();
    vi.setSystemTime(fixedInstant);

    expect(nowLocalDate()).toBe("2026-03-01");
    expect(nowLocalTime()).toBe("21:30");
    expect(nowLocalDateTime()).toBe("2026-03-01T21:30");

    // The bug this replaces would have produced the UTC slice instead --
    // explicitly prove the two genuinely differ here.
    expect(fixedInstant.toISOString().slice(0, 10)).toBe("2026-03-02");
    expect(fixedInstant.toISOString().slice(11, 16)).toBe("02:30");
  });
});
