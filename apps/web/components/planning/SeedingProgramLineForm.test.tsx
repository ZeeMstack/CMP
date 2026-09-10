import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { withQueryClient } from "@/lib/test-utils";

import { SeedingProgramLineForm } from "./SeedingProgramLineForm";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const VARIETIES = [{ id: "var-1", code: "PANG", name: "Pangkor" }];
const UOMS = [
  { id: "uom-kg", code: "kg", name: "Kilogram", quantity_kind: "mass" },
  { id: "uom-seed", code: "SEED", name: "Seed", quantity_kind: "count" },
  { id: "uom-ea", code: "EA", name: "Each", quantity_kind: "count" },
];

function stubFetch() {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/varieties")) return jsonResponse(VARIETIES);
      if (url.includes("/uoms")) return jsonResponse(UOMS);
      return jsonResponse([]);
    }),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("SeedingProgramLineForm", () => {
  it("submits a plan line payload carrying the parent requirement's crop and coverage UOM, never asking the planner to re-pick them", async () => {
    stubFetch();
    const onSubmit = vi.fn();
    render(
      withQueryClient(
        <SeedingProgramLineForm
          cropId="crop-1"
          cropName="Iceberg Lettuce"
          expectedCoverageUomId="uom-kg"
          expectedCoverageUomCode="kg"
          onSubmit={onSubmit}
          isSubmitting={false}
        />,
      ),
    );

    await waitFor(() => expect(screen.getByText("Pangkor")).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText(/variety/i), { target: { value: "var-1" } });
    fireEvent.change(screen.getByLabelText(/planned sow date/i), { target: { value: "2026-09-01" } });
    fireEvent.change(screen.getByLabelText(/planned sowing quantity/i), { target: { value: "20000" } });
    fireEvent.change(screen.getByLabelText(/^unit$/i), { target: { value: "uom-seed" } });
    fireEvent.change(screen.getByLabelText(/expected coverage/i), { target: { value: "10000" } });
    fireEvent.click(screen.getByRole("button", { name: /add plan line/i }));

    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
    const payload = onSubmit.mock.calls[0][0];
    expect(payload).toMatchObject({
      crop_id: "crop-1", variety_id: "var-1", planned_sow_date: "2026-09-01",
      planned_quantity: "20000", planned_quantity_uom_id: "uom-seed",
      expected_coverage_quantity: "10000", expected_coverage_uom_id: "uom-kg",
    });
  });

  it("only offers count-kind units for planned sowing quantity, never kg", async () => {
    stubFetch();
    render(
      withQueryClient(
        <SeedingProgramLineForm
          cropId="crop-1"
          cropName="Iceberg Lettuce"
          expectedCoverageUomId="uom-kg"
          expectedCoverageUomCode="kg"
          onSubmit={vi.fn()}
          isSubmitting={false}
        />,
      ),
    );

    await waitFor(() => expect(screen.getByRole("option", { name: "SEED" })).toBeInTheDocument());
    const unitSelect = screen.getByLabelText(/^unit$/i) as HTMLSelectElement;
    const optionValues = Array.from(unitSelect.options).map((o) => o.textContent);
    expect(optionValues).toContain("SEED");
    expect(optionValues).toContain("EA");
    expect(optionValues).not.toContain("kg");
  });
});
