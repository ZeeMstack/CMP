import { describe, expect, it } from "vitest";

import { formatElapsedSince } from "./elapsed";

describe("formatElapsedSince", () => {
  const now = new Date("2026-01-02T12:00:00Z");

  it("reports just now for under a minute", () => {
    expect(formatElapsedSince("2026-01-02T11:59:30Z", now)).toBe("just now");
  });

  it("reports minutes under an hour", () => {
    expect(formatElapsedSince("2026-01-02T11:45:00Z", now)).toBe("15m in state");
  });

  it("reports hours under a day", () => {
    expect(formatElapsedSince("2026-01-02T08:00:00Z", now)).toBe("4h in state");
  });

  it("reports days at or beyond 24h", () => {
    expect(formatElapsedSince("2025-12-31T12:00:00Z", now)).toBe("2d in state");
  });
});
