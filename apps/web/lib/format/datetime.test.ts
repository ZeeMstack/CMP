import { describe, expect, it } from "vitest";

import { formatDateTime, formatDateTimeWithZoneLabel } from "./datetime";

describe("formatDateTime", () => {
  it("returns an em dash for null/undefined/empty input", () => {
    expect(formatDateTime(null)).toBe("—");
    expect(formatDateTime(undefined)).toBe("—");
    expect(formatDateTime("")).toBe("—");
  });

  it("returns an em dash for an unparsable value", () => {
    expect(formatDateTime("not-a-date")).toBe("—");
  });

  it("formats a valid ISO value in a given IANA timezone", () => {
    const formatted = formatDateTime("2026-01-15T12:00:00Z", "Asia/Karachi");
    expect(formatted).not.toBe("—");
    // 12:00 UTC is 17:00 in Asia/Karachi (UTC+5) -- assert the hour shows up.
    expect(formatted).toMatch(/5:00|17:00/);
  });

  it("still formats without a timezone (browser-local fallback)", () => {
    expect(formatDateTime("2026-01-15T12:00:00Z")).not.toBe("—");
  });
});

describe("formatDateTimeWithZoneLabel", () => {
  it("appends the timezone name when provided", () => {
    expect(formatDateTimeWithZoneLabel("2026-01-15T12:00:00Z", "Asia/Karachi")).toContain("Asia/Karachi");
  });

  it("labels the fallback as local time when no timezone is known", () => {
    expect(formatDateTimeWithZoneLabel("2026-01-15T12:00:00Z")).toContain("your local time");
  });

  it("passes through the em dash for missing values", () => {
    expect(formatDateTimeWithZoneLabel(null, "Asia/Karachi")).toBe("—");
  });
});
