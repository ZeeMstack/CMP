import { describe, expect, it } from "vitest";

import { DEFAULT_HARVEST_FORECAST_FORM_VALUES, harvestForecastFormSchema } from "@/lib/validation/harvestForecast";

const VALID = {
  ...DEFAULT_HARVEST_FORECAST_FORM_VALUES,
  window_start_date: "2026-10-01",
  window_end_date: "2026-10-08",
  low_quantity: "800",
  expected_quantity: "1000",
  high_quantity: "1200",
  quantity_uom_id: "uom-kg",
  basis: "grower_estimate" as const,
};

describe("harvestForecastFormSchema", () => {
  it("accepts a valid LOW <= EXPECTED <= HIGH window", () => {
    expect(harvestForecastFormSchema.safeParse(VALID).success).toBe(true);
  });

  it("rejects LOW greater than EXPECTED", () => {
    const result = harvestForecastFormSchema.safeParse({ ...VALID, low_quantity: "1100" });
    expect(result.success).toBe(false);
  });

  it("rejects EXPECTED greater than HIGH", () => {
    const result = harvestForecastFormSchema.safeParse({ ...VALID, high_quantity: "900" });
    expect(result.success).toBe(false);
  });

  it("rejects a window end before window start", () => {
    const result = harvestForecastFormSchema.safeParse({
      ...VALID,
      window_start_date: "2026-10-08",
      window_end_date: "2026-10-01",
    });
    expect(result.success).toBe(false);
  });
});
