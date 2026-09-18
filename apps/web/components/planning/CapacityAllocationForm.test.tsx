import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { FlattenedLocationCapacityOption } from "@/lib/format/locationTree";
import { withQueryClient } from "@/lib/test-utils";

import { CapacityAllocationForm } from "./CapacityAllocationForm";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const LOCATIONS: FlattenedLocationCapacityOption[] = [
  { id: "loc-1", code: "GT-01", name: "Grow Table 01", label: "Grow Table 01 (GT-01)", depth: 0, status: "active", occupiable: true, capacity: 1200 },
];

function stubFetch() {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/capacity-summary")) {
        return jsonResponse({
          location_id: "loc-1", location_code: "GT-01", window_start_date: "2026-10-01", window_end_date: "2026-10-08",
          capacity_status: "known", authoritative_capacity: 1200, capacity_unit: "position",
          planned_used_capacity: 1000, available_planned_capacity: 200, allocations: [],
        });
      }
      return jsonResponse([]);
    }),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("CapacityAllocationForm", () => {
  it("PILOT-PLAN-001B section 12: pre-submit preview shows Configured/Already planned/Requested/Remaining from the authoritative capacity-summary read", async () => {
    stubFetch();
    render(
      withQueryClient(
        <CapacityAllocationForm
          farmId="farm-1"
          locationOptions={LOCATIONS}
          defaultLocationId="loc-1"
          onSubmit={vi.fn()}
          onCancel={vi.fn()}
          isSubmitting={false}
        />,
      ),
    );

    fireEvent.change(screen.getByLabelText(/^start$/i), { target: { value: "2026-10-01" } });
    fireEvent.change(screen.getByLabelText(/end \(exclusive\)/i), { target: { value: "2026-10-08" } });
    fireEvent.change(screen.getByLabelText(/planned positions/i), { target: { value: "150" } });

    await waitFor(() => expect(screen.getByText("1200 positions")).toBeInTheDocument());
    expect(screen.getByText("1000 positions")).toBeInTheDocument();
    expect(screen.getByText("150 positions")).toBeInTheDocument();
    // Remaining after this = 200 (available) - 150 (requested) = 50.
    expect(screen.getByText("50 positions")).toBeInTheDocument();
  });

  it("PILOT-PLAN-001B section 13: an over-capacity rejection shows the backend's own message truthfully and preserves the entered form", async () => {
    stubFetch();
    render(
      withQueryClient(
        <CapacityAllocationForm
          farmId="farm-1"
          locationOptions={LOCATIONS}
          defaultLocationId="loc-1"
          onSubmit={vi.fn()}
          onCancel={vi.fn()}
          isSubmitting={false}
          serverError="Location GT-01: overlapping planned capacity (1400 positions) would exceed authoritative capacity (1200 positions)."
        />,
      ),
    );

    fireEvent.change(screen.getByLabelText(/planned positions/i), { target: { value: "400" } });

    expect(screen.getByRole("alert")).toHaveTextContent(
      "Location GT-01: overlapping planned capacity (1400 positions) would exceed authoritative capacity (1200 positions).",
    );
    // The requested amount the user typed is still there -- never silently cleared or reduced.
    expect(screen.getByLabelText(/planned positions/i)).toHaveValue("400");
  });
});
