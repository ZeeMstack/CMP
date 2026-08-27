import { describe, expect, it } from "vitest";

import { isVersionSelectableAt, selectableVersionsAt, type VersionLifecycle } from "./versionLifecycle";

function version(overrides: Partial<VersionLifecycle> = {}): VersionLifecycle {
  return { status: "active", effective_from: "2026-01-01T00:00:00Z", effective_until: null, ...overrides };
}

describe("isVersionSelectableAt", () => {
  it("a DRAFT version is never selectable, regardless of effective_time", () => {
    expect(isVersionSelectableAt(version({ status: "draft", effective_from: null }), "2026-06-01T00:00:00Z")).toBe(false);
  });

  it("an ACTIVE version with no effective_until is selectable at or after effective_from", () => {
    const v = version({ status: "active", effective_from: "2026-01-01T00:00:00Z", effective_until: null });
    expect(isVersionSelectableAt(v, "2026-01-01T00:00:00Z")).toBe(true);
    expect(isVersionSelectableAt(v, "2026-06-01T00:00:00Z")).toBe(true);
  });

  it("a currently-ACTIVE version is NOT selectable for a transaction backdated before its own effective_from", () => {
    const v = version({ status: "active", effective_from: "2026-03-01T00:00:00Z", effective_until: null });
    expect(isVersionSelectableAt(v, "2026-02-15T00:00:00Z")).toBe(false);
  });

  it("a historically-valid RETIRED version is selectable inside its own [from, until) window", () => {
    const v = version({ status: "retired", effective_from: "2026-01-01T00:00:00Z", effective_until: "2026-03-01T00:00:00Z" });
    expect(isVersionSelectableAt(v, "2026-02-01T00:00:00Z")).toBe(true);
    // Boundary: effective_from is inclusive.
    expect(isVersionSelectableAt(v, "2026-01-01T00:00:00Z")).toBe(true);
  });

  it("a RETIRED version is NOT selectable at or after its own effective_until (exclusive upper bound)", () => {
    const v = version({ status: "retired", effective_from: "2026-01-01T00:00:00Z", effective_until: "2026-03-01T00:00:00Z" });
    expect(isVersionSelectableAt(v, "2026-03-01T00:00:00Z")).toBe(false);
    expect(isVersionSelectableAt(v, "2026-04-01T00:00:00Z")).toBe(false);
  });

  it("a RETIRED version is NOT selectable before its own effective_from", () => {
    const v = version({ status: "retired", effective_from: "2026-01-01T00:00:00Z", effective_until: "2026-03-01T00:00:00Z" });
    expect(isVersionSelectableAt(v, "2025-12-01T00:00:00Z")).toBe(false);
  });

  it("a version with no effective_from (never activated) is never selectable even if status is not draft", () => {
    expect(isVersionSelectableAt(version({ status: "active", effective_from: null }), "2026-06-01T00:00:00Z")).toBe(false);
  });

  it("an empty effectiveTimeIso is never selectable", () => {
    expect(isVersionSelectableAt(version(), "")).toBe(false);
  });
});

describe("selectableVersionsAt", () => {
  it("filters a mixed list down to only the historically-valid ACTIVE/RETIRED versions at the given time", () => {
    const draft = version({ status: "draft", effective_from: null });
    const activeNow = version({ status: "active", effective_from: "2026-01-01T00:00:00Z", effective_until: null });
    const retiredInWindow = version({
      status: "retired", effective_from: "2025-01-01T00:00:00Z", effective_until: "2026-01-01T00:00:00Z",
    });
    const retiredOutOfWindow = version({
      status: "retired", effective_from: "2024-01-01T00:00:00Z", effective_until: "2025-01-01T00:00:00Z",
    });

    const result = selectableVersionsAt(
      [draft, activeNow, retiredInWindow, retiredOutOfWindow],
      "2025-06-01T00:00:00Z",
    );
    expect(result).toEqual([retiredInWindow]);
  });
});
