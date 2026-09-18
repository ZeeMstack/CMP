import { describe, expect, it } from "vitest";

import type { LocationCapacitySummaryRead } from "@/lib/api/client";
import { CAPACITY_STATUS_LABEL, deriveCapacityStatus } from "@/lib/format/capacityStatus";

function summary(overrides: Partial<LocationCapacitySummaryRead> = {}): LocationCapacitySummaryRead {
  return {
    location_id: "loc-1",
    location_code: "GT-01",
    window_start_date: "2026-10-01",
    window_end_date: "2026-10-08",
    capacity_status: "known",
    authoritative_capacity: 1200,
    capacity_unit: "position",
    planned_used_capacity: 1000,
    available_planned_capacity: 200,
    allocations: [],
    ...overrides,
  };
}

describe("deriveCapacityStatus", () => {
  it("UNKNOWN never shows a fabricated available amount when capacity is not configured", () => {
    const result = summary({ capacity_status: "unknown", authoritative_capacity: null, available_planned_capacity: null });
    expect(deriveCapacityStatus(result)).toBe("UNKNOWN");
    expect(CAPACITY_STATUS_LABEL[deriveCapacityStatus(result)]).toBe("Unknown capacity");
    expect(deriveCapacityStatus(undefined)).toBe("UNKNOWN");
  });

  it("NO_ALLOCATION when nothing is planned yet, distinct from AVAILABLE -- planned and authoritative are never conflated", () => {
    expect(deriveCapacityStatus(summary({ planned_used_capacity: 0, available_planned_capacity: 1200 }))).toBe(
      "NO_ALLOCATION",
    );
  });

  it("AVAILABLE when some planned capacity remains", () => {
    expect(deriveCapacityStatus(summary({ planned_used_capacity: 1000, available_planned_capacity: 200 }))).toBe(
      "AVAILABLE",
    );
  });

  it("FULL when planned usage exactly meets configured capacity", () => {
    expect(deriveCapacityStatus(summary({ planned_used_capacity: 1200, available_planned_capacity: 0 }))).toBe("FULL");
  });

  it("OVER_COMMITTED when planned usage exceeds configured capacity", () => {
    expect(deriveCapacityStatus(summary({ planned_used_capacity: 1300, available_planned_capacity: -100 }))).toBe(
      "OVER_COMMITTED",
    );
  });
});
