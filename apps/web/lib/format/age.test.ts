import { describe, expect, it } from "vitest";

import { calendarDaysBetween, describeSowingAndAge, formatDateOnly } from "./age";

describe("calendarDaysBetween", () => {
  it("returns 0 for the same farm-local calendar date", () => {
    expect(calendarDaysBetween("2026-06-08T08:00:00Z", "UTC", new Date("2026-06-08T20:00:00Z"))).toBe(0);
  });

  it("returns a whole day count, not a fractional 24-hour-period count", () => {
    // 62 days later, well within the same time-of-day -- must be exactly 62.
    expect(calendarDaysBetween("2026-06-08T08:00:00Z", "UTC", new Date("2026-08-09T08:00:00Z"))).toBe(62);
  });

  it("is timezone-safe across a farm-local midnight boundary browser-UTC would miss", () => {
    // 23:50 in Asia/Dubai (UTC+4) on 2026-06-08 is 19:50 UTC on 2026-06-08.
    const sownAt = "2026-06-08T19:50:00Z";
    // Ten minutes later in real time -- 00:00 Asia/Dubai on 2026-06-09 --
    // the farm-local calendar date has already rolled over to the next
    // day, so this must read as 1 day old, not 0.
    const tenMinutesLater = new Date("2026-06-08T20:00:00Z");
    expect(calendarDaysBetween(sownAt, "Asia/Dubai", tenMinutesLater)).toBe(1);
    // The same real-time gap in UTC (no timezone rollover) is still 0 days.
    expect(calendarDaysBetween(sownAt, "UTC", tenMinutesLater)).toBe(0);
  });
});

describe("formatDateOnly", () => {
  it("formats an ISO instant as a farm-local date only, no time component", () => {
    const formatted = formatDateOnly("2026-06-08T20:00:00Z", "UTC");
    expect(formatted).toMatch(/08 Jun 2026/);
  });
});

describe("describeSowingAndAge", () => {
  it("returns a known sown date + whole-day age when sown_effective_time is present", () => {
    const result = describeSowingAndAge(1, "2026-06-08T08:00:00Z", "UTC", new Date("2026-08-09T08:00:00Z"));
    expect(result).toEqual({ kind: "known", sownDateLabel: expect.stringContaining("2026"), ageDays: 62 });
  });

  it("never invents an age when sown_effective_time is null but multiple origins exist", () => {
    const result = describeSowingAndAge(2, null, "UTC");
    expect(result).toEqual({ kind: "multiple_origins" });
  });

  it("reports an honest unknown state when there are no sowing origins at all", () => {
    const result = describeSowingAndAge(0, null, "UTC");
    expect(result).toEqual({ kind: "unknown" });
  });
});
