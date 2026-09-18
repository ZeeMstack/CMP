import { describe, expect, it } from "vitest";

import type { RequirementHarvestOutlook } from "@/lib/api/client";
import { COVERAGE_STATUS_LABEL, deriveCoverageStatus } from "@/lib/format/forecastCoverage";

const KG_UOM = { id: "uom-kg", code: "kg", name: "Kilogram", quantity_kind: "mass" };

function outlook(overrides: Partial<RequirementHarvestOutlook> = {}): RequirementHarvestOutlook {
  return {
    requirement_id: "req-1",
    required_quantity: "10000",
    required_uom: KG_UOM,
    contributing_batch_count: 2,
    batches_with_current_forecast_count: 2,
    forecast_comparable: true,
    forecast_low_quantity: "8000",
    forecast_expected_quantity: "9000",
    forecast_high_quantity: "10500",
    coverage_gap_quantity: "1000",
    actual_harvested_comparable: true,
    actual_harvested_quantity: "500",
    actual_harvested_weight_kg: "500",
    ...overrides,
  };
}

describe("deriveCoverageStatus", () => {
  it("SHORT when the coverage gap is positive", () => {
    expect(deriveCoverageStatus(outlook({ coverage_gap_quantity: "1000" }))).toBe("SHORT");
  });

  it("COVERED when the coverage gap is exactly zero", () => {
    expect(deriveCoverageStatus(outlook({ coverage_gap_quantity: "0" }))).toBe("COVERED");
  });

  it("OVER when the coverage gap is negative (forecast exceeds demand)", () => {
    expect(deriveCoverageStatus(outlook({ coverage_gap_quantity: "-500" }))).toBe("OVER");
  });

  it("NOT_COMPARABLE when the backend could not resolve a UOM conversion, never a fabricated coverage number", () => {
    const result = outlook({
      forecast_comparable: false,
      forecast_expected_quantity: null,
      coverage_gap_quantity: null,
    });
    expect(deriveCoverageStatus(result)).toBe("NOT_COMPARABLE");
    expect(COVERAGE_STATUS_LABEL[deriveCoverageStatus(result)]).toBe("Not comparable");
  });

  it("NO_FORECAST when no contributing batch has a current forecast, and when the outlook itself is missing", () => {
    expect(deriveCoverageStatus(outlook({ batches_with_current_forecast_count: 0 }))).toBe("NO_FORECAST");
    expect(deriveCoverageStatus(undefined)).toBe("NO_FORECAST");
  });
});
