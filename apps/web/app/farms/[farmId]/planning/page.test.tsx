import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useParams: () => ({ farmId: "farm-1" }),
}));

import { withQueryClient } from "@/lib/test-utils";

import PlanningPage from "./page";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const KG_UOM = { id: "uom-kg", code: "kg", name: "Kilogram", quantity_kind: "mass" };
const SEED_UOM = { id: "uom-seed", code: "SEED", name: "Seed", quantity_kind: "count" };

function requirement(overrides: Record<string, unknown> = {}) {
  return {
    id: "req-1", tenant_id: "t", farm_id: "farm-1", code: "PR-2026-001",
    crop: { id: "crop-1", code: "ICE", common_name: "Iceberg Lettuce" },
    variety: { id: "var-1", code: "PANG", name: "Pangkor" },
    required_by_date: "2026-10-15", required_quantity: "30000", uom: KG_UOM,
    reference: "Customer A", notes: null, status: "open",
    created_by_user_id: "u1", created_at: "2026-09-01T00:00:00Z", updated_at: "2026-09-01T00:00:00Z",
    fulfillment: {
      demand_quantity: "30000", planned_coverage_quantity: "25000", gap_quantity: "5000",
      is_overplanned: false, overplanned_quantity: "0", planned_lines_count: 3, actual_sowings_count: 0,
    },
    ...overrides,
  };
}

function line(overrides: Record<string, unknown> = {}) {
  return {
    id: "line-1", tenant_id: "t", farm_id: "farm-1", production_requirement_id: "req-1",
    requirement_code: "PR-2026-001", planned_sow_date: "2026-09-01",
    crop: { id: "crop-1", code: "ICE", common_name: "Iceberg Lettuce" },
    variety: { id: "var-1", code: "PANG", name: "Pangkor" },
    planned_quantity: "20000", planned_quantity_uom: SEED_UOM,
    expected_coverage_quantity: "10000", expected_coverage_uom: KG_UOM,
    notes: null, status: "planned", linked_sowing_count: 0,
    created_by_user_id: "u1", created_at: "2026-08-01T00:00:00Z", updated_at: "2026-08-01T00:00:00Z",
    ...overrides,
  };
}

function stubFetch(overrides: { requirements?: unknown; lines?: unknown } = {}) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/production-requirements")) return jsonResponse(overrides.requirements ?? [requirement()]);
      if (url.includes("/seeding-program-lines")) return jsonResponse(overrides.lines ?? [line()]);
      return jsonResponse([]);
    }),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("PlanningPage", () => {
  it("renders the Requirements table with demand/planned/gap and a compact 'Plan' action, never a raw status literal", async () => {
    stubFetch();
    render(withQueryClient(<PlanningPage />));

    await waitFor(() => expect(screen.getByText("Iceberg Lettuce")).toBeInTheDocument());
    expect(screen.getByText("Pangkor")).toBeInTheDocument();
    expect(screen.getByText("30,000 kg")).toBeInTheDocument();
    expect(screen.getByText("25,000 kg")).toBeInTheDocument();
    expect(screen.getByText("5,000 kg")).toBeInTheDocument();
    // Status is a friendly label ("Open"), never the raw enum value.
    expect(screen.getByText("Open")).toBeInTheDocument();
    expect(screen.queryByText("open")).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Plan" })).toHaveAttribute(
      "href",
      "/farms/farm-1/planning/requirements/req-1",
    );
  });

  it("shows an overplanned requirement's overplanned amount instead of a negative gap", async () => {
    stubFetch({
      requirements: [
        requirement({
          fulfillment: {
            demand_quantity: "10000", planned_coverage_quantity: "15000", gap_quantity: "0",
            is_overplanned: true, overplanned_quantity: "5000", planned_lines_count: 1, actual_sowings_count: 0,
          },
        }),
      ],
    });
    render(withQueryClient(<PlanningPage />));

    await waitFor(() => expect(screen.getByText(/5,000 kg over/)).toBeInTheDocument());
  });

  it("switches to the Seeding Program tab and shows a Sow Now action linking to the existing Sowing workflow with plan prefill", async () => {
    stubFetch();
    render(withQueryClient(<PlanningPage />));

    await waitFor(() => expect(screen.getByText("Iceberg Lettuce")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("tab", { name: "Seeding Program" }));

    await waitFor(() => expect(screen.getByText("20,000 SEED")).toBeInTheDocument());
    expect(screen.getByText("10,000 kg")).toBeInTheDocument();
    const sowNow = screen.getByRole("link", { name: "Sow now" });
    expect(sowNow.getAttribute("href")).toContain("/farms/farm-1/nursery/sowings/new?");
    expect(sowNow.getAttribute("href")).toContain("seeding_program_line_id=line-1");
    expect(sowNow.getAttribute("href")).toContain("crop_id=crop-1");
  });

  it("PILOT-UX-003: reflects a plan line with linked Sowings as 'Sowing recorded', never a false 'Complete'", async () => {
    // `linked_sowing_count` is a RECORD COUNT, not a sown quantity -- it
    // must never be presented as proof the planned quantity was fully sown.
    stubFetch({ lines: [line({ status: "planned", linked_sowing_count: 2 })] });
    render(withQueryClient(<PlanningPage />));
    fireEvent.click(screen.getByRole("tab", { name: "Seeding Program" }));

    await waitFor(() => expect(screen.getByText("Sowing recorded")).toBeInTheDocument());
    expect(screen.getByText("2 sowing records")).toBeInTheDocument();
    expect(screen.queryByText("Complete")).not.toBeInTheDocument();
  });

  it("shows a cancelled plan line with no Sow Now action, but keeps it visible (never hard-deleted)", async () => {
    stubFetch({ lines: [line({ status: "cancelled" })] });
    render(withQueryClient(<PlanningPage />));
    fireEvent.click(screen.getByRole("tab", { name: "Seeding Program" }));

    await waitFor(() => expect(screen.getByText("Cancelled")).toBeInTheDocument());
    expect(screen.queryByRole("link", { name: "Sow now" })).not.toBeInTheDocument();
  });

  it("shows an empty state with a primary action when no requirements exist", async () => {
    stubFetch({ requirements: [] });
    render(withQueryClient(<PlanningPage />));

    await waitFor(() => expect(screen.getByText("No production requirements yet.")).toBeInTheDocument());
    expect(screen.getAllByRole("link", { name: /production requirement/i })[0]).toHaveAttribute(
      "href",
      "/farms/farm-1/planning/requirements/new",
    );
  });
});
