import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { withQueryClient } from "@/lib/test-utils";

import { CapacityOutlookTable } from "./CapacityOutlookTable";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const ALLOCATION = {
  id: "alloc-1", tenant_id: "t", farm_id: "farm-1", code: "CAP-2026-001",
  location_id: "loc-1", location_code: "GT-01", production_system_id: null,
  planned_start_date: "2026-10-01", planned_end_date: "2026-10-08", planned_capacity_amount: 200,
  capacity_unit: "position", source_seeding_program_line_id: null, source_crop_batch_id: null,
  status: "active", notes: null,
  created_by_user_id: "u1", created_at: "2026-09-01T00:00:00Z", updated_at: "2026-09-01T00:00:00Z",
  cancelled_by_user_id: null, cancelled_at: null,
};

const LOCATION_TREE = [
  { id: "loc-1", code: "GT-01", name: "Grow Table 01", location_type_id: "lt-1", location_type_code: "GROW_TABLE", status: "active", occupiable: true, capacity: null, children: [] },
];

function stubFetch(overrides: { summaryStatus?: "known" | "unknown"; allocationsError?: boolean } = {}) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/capacity-summary")) {
        return jsonResponse(
          overrides.summaryStatus === "unknown"
            ? {
                location_id: "loc-1", location_code: "GT-01", window_start_date: "2026-10-01", window_end_date: "2026-11-01",
                capacity_status: "unknown", authoritative_capacity: null, capacity_unit: "position",
                planned_used_capacity: 0, available_planned_capacity: null, allocations: [],
              }
            : {
                location_id: "loc-1", location_code: "GT-01", window_start_date: "2026-10-01", window_end_date: "2026-11-01",
                capacity_status: "known", authoritative_capacity: 1200, capacity_unit: "position",
                planned_used_capacity: 200, available_planned_capacity: 1000, allocations: [ALLOCATION],
              },
        );
      }
      if (url.includes("/locations/tree")) return jsonResponse(LOCATION_TREE);
      if (url.includes("/capacity-allocations")) {
        if (overrides.allocationsError) return jsonResponse({ detail: "Server error" }, 500);
        return jsonResponse([ALLOCATION]);
      }
      return jsonResponse([]);
    }),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("CapacityOutlookTable", () => {
  it("UNKNOWN capacity shows 'Capacity not configured', never a fabricated or unlimited number", async () => {
    stubFetch({ summaryStatus: "unknown" });
    render(withQueryClient(<CapacityOutlookTable farmId="farm-1" periodStart="2026-10-01" periodEnd="2026-11-01" />));

    await waitFor(() => expect(screen.getByText("Capacity not configured")).toBeInTheDocument());
    expect(screen.getByText("Unknown capacity")).toBeInTheDocument();
    expect(screen.queryByText(/unlimited/i)).not.toBeInTheDocument();
  });

  it("keeps Authoritative capacity and Planned allocation in separate columns -- never conflates configured capacity with what's planned", async () => {
    stubFetch({ summaryStatus: "known" });
    render(withQueryClient(<CapacityOutlookTable farmId="farm-1" periodStart="2026-10-01" periodEnd="2026-11-01" />));

    await waitFor(() => expect(screen.getByText("1200")).toBeInTheDocument());
    expect(screen.getByText("200")).toBeInTheDocument();
    expect(screen.getByText("1000 planned available")).toBeInTheDocument();
    expect(screen.getByText("Available")).toBeInTheDocument();
  });

  it("an allocations-list failure shows the error state, never an empty-looking outlook table", async () => {
    stubFetch({ allocationsError: true });
    render(withQueryClient(<CapacityOutlookTable farmId="farm-1" periodStart="2026-10-01" periodEnd="2026-11-01" />));

    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
    expect(screen.queryByText("No locations tracked in this outlook yet.")).not.toBeInTheDocument();
  });
});
