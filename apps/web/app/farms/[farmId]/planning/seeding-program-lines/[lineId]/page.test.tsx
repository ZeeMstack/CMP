import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useParams: () => ({ farmId: "farm-1", lineId: "line-1" }),
}));

import { withQueryClient } from "@/lib/test-utils";

import SeedingProgramLineDetailPage from "./page";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const KG_UOM = { id: "uom-kg", code: "kg", name: "Kilogram", quantity_kind: "mass" };
const SEED_UOM = { id: "uom-seed", code: "SEED", name: "Seed", quantity_kind: "count" };

function lineDetail(overrides: Record<string, unknown> = {}) {
  return {
    id: "line-1", tenant_id: "t", farm_id: "farm-1", production_requirement_id: "req-1",
    requirement_code: "PR-2026-001", planned_sow_date: "2026-09-01",
    crop: { id: "crop-1", code: "ICE", common_name: "Iceberg Lettuce" },
    variety: { id: "var-1", code: "PANG", name: "Pangkor" },
    planned_quantity: "20000", planned_quantity_uom: SEED_UOM,
    expected_coverage_quantity: "10000", expected_coverage_uom: KG_UOM,
    notes: null, status: "planned", linked_sowing_count: 0,
    created_by_user_id: "u1", created_at: "2026-08-01T00:00:00Z", updated_at: "2026-08-01T00:00:00Z",
    linked_sowings: [],
    ...overrides,
  };
}

function stubFetch(detail: unknown) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/seeding-program-lines/line-1")) return jsonResponse(detail);
      return jsonResponse([]);
    }),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("SeedingProgramLineDetailPage", () => {
  it("hands off 'Sow Now' to the existing Sowing workflow, prefilled with the plan line/crop/variety -- never a second Sowing form", async () => {
    stubFetch(lineDetail());
    render(withQueryClient(<SeedingProgramLineDetailPage />));

    await waitFor(() => expect(screen.getByRole("link", { name: "Sow now" })).toBeInTheDocument());
    const href = screen.getByRole("link", { name: "Sow now" }).getAttribute("href");
    expect(href).toBe(
      "/farms/farm-1/nursery/sowings/new?seeding_program_line_id=line-1&crop_id=crop-1&variety_id=var-1",
    );
  });

  it("shows an honest 'not sown yet' state before any actual Sowing links -- never claims a harvest quantity", async () => {
    stubFetch(lineDetail());
    render(withQueryClient(<SeedingProgramLineDetailPage />));

    await waitFor(() => expect(screen.getByText(/not sown yet/i)).toBeInTheDocument());
    expect(screen.queryByText(/kg harvested/i)).not.toBeInTheDocument();
  });

  it("reflects each actual linked Sowing by real batch code once execution has begun", async () => {
    stubFetch(
      lineDetail({
        linked_sowing_count: 1,
        linked_sowings: [
          { id: "sow-1", batch_id: "batch-1", batch_code: "ICE-0001", effective_time: "2026-09-01T08:00:00Z", total_seeds_sown: 20000 },
        ],
      }),
    );
    render(withQueryClient(<SeedingProgramLineDetailPage />));

    await waitFor(() => expect(screen.getByText("ICE-0001")).toBeInTheDocument());
    expect(screen.getByText(/20000 seeds sown/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "ICE-0001" })).toHaveAttribute(
      "href",
      "/farms/farm-1/crop-batches/batch-1?tab=sowing",
    );
  });

  it("hides Sow Now and Cancel once a plan line is cancelled, but keeps it viewable", async () => {
    stubFetch(lineDetail({ status: "cancelled" }));
    render(withQueryClient(<SeedingProgramLineDetailPage />));

    await waitFor(() => expect(screen.getByText("Cancelled")).toBeInTheDocument());
    expect(screen.queryByRole("link", { name: "Sow now" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /cancel plan line/i })).not.toBeInTheDocument();
  });
});
