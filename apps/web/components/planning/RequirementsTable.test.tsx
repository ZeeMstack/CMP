import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { ProductionRequirementRead, RequirementHarvestOutlook } from "@/lib/api/client";

import { RequirementsTable } from "./RequirementsTable";

const KG_UOM = { id: "uom-kg", code: "kg", name: "Kilogram", quantity_kind: "mass" };

function requirement(overrides: Partial<ProductionRequirementRead> = {}): ProductionRequirementRead {
  return {
    id: "req-1", tenant_id: "t", farm_id: "farm-1", code: "PR-2026-001",
    crop: { id: "crop-1", code: "ICE", common_name: "Iceberg Lettuce" },
    variety: null,
    required_by_date: "2026-10-15", required_quantity: "30000", uom: KG_UOM,
    reference: null, notes: null, status: "open",
    created_by_user_id: "u1", created_at: "2026-09-01T00:00:00Z", updated_at: "2026-09-01T00:00:00Z",
    fulfillment: {
      demand_quantity: "30000", planned_coverage_quantity: "25000", gap_quantity: "5000",
      is_overplanned: false, overplanned_quantity: "0", planned_lines_count: 3, actual_sowings_count: 1,
    },
    ...overrides,
  } as ProductionRequirementRead;
}

function outlook(overrides: Partial<RequirementHarvestOutlook> = {}): RequirementHarvestOutlook {
  return {
    requirement_id: "req-1", required_quantity: "30000", required_uom: KG_UOM,
    contributing_batch_count: 1, batches_with_current_forecast_count: 1,
    forecast_comparable: true, forecast_low_quantity: "24000", forecast_expected_quantity: "28000",
    forecast_high_quantity: "31000", coverage_gap_quantity: "2000",
    actual_harvested_comparable: true, actual_harvested_quantity: "5000", actual_harvested_weight_kg: "5000",
    ...overrides,
  };
}

describe("RequirementsTable", () => {
  it("without an outlook map, renders exactly as before (no Forecast/Harvested/Outlook columns)", () => {
    render(<RequirementsTable requirements={[requirement()]} farmId="farm-1" />);
    expect(screen.queryByText("Outlook")).not.toBeInTheDocument();
    expect(screen.queryByText("Forecast (expected)")).not.toBeInTheDocument();
  });

  it("SHORT: a positive coverage gap renders the Short outlook badge", () => {
    render(
      <RequirementsTable
        requirements={[requirement()]}
        farmId="farm-1"
        outlookByRequirementId={{ "req-1": outlook({ coverage_gap_quantity: "2000" }) }}
      />,
    );
    expect(screen.getByText("Short")).toBeInTheDocument();
    expect(screen.getByText("28,000 kg")).toBeInTheDocument();
  });

  it("COVERED: a zero coverage gap renders the Covered outlook badge", () => {
    render(
      <RequirementsTable
        requirements={[requirement()]}
        farmId="farm-1"
        outlookByRequirementId={{ "req-1": outlook({ coverage_gap_quantity: "0" }) }}
      />,
    );
    expect(screen.getByText("Covered")).toBeInTheDocument();
  });

  it("OVER: a negative coverage gap renders the Over outlook badge", () => {
    render(
      <RequirementsTable
        requirements={[requirement()]}
        farmId="farm-1"
        outlookByRequirementId={{ "req-1": outlook({ coverage_gap_quantity: "-1000" }) }}
      />,
    );
    expect(screen.getByText("Over")).toBeInTheDocument();
  });

  it("an incompatible UOM shows 'Not comparable' text, never a fake percentage or number", () => {
    render(
      <RequirementsTable
        requirements={[requirement()]}
        farmId="farm-1"
        outlookByRequirementId={{
          "req-1": outlook({ forecast_comparable: false, forecast_expected_quantity: null, coverage_gap_quantity: null }),
        }}
      />,
    );
    expect(screen.getAllByText("Not comparable").length).toBeGreaterThan(0);
    expect(screen.queryByText(/%/)).not.toBeInTheDocument();
  });

  it("NO_FORECAST: no contributing batch with a current forecast shows 'No forecast', not a zeroed number", () => {
    render(
      <RequirementsTable
        requirements={[requirement()]}
        farmId="farm-1"
        outlookByRequirementId={{
          "req-1": outlook({
            batches_with_current_forecast_count: 0,
            forecast_comparable: false,
            forecast_expected_quantity: null,
            coverage_gap_quantity: null,
          }),
        }}
      />,
    );
    expect(screen.getAllByText("No forecast").length).toBeGreaterThanOrEqual(2);
  });
});
