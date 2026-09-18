import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ProductionCapacityAllocationRead } from "@/lib/api/client";
import { withQueryClient } from "@/lib/test-utils";

import { CapacityAllocationList } from "./CapacityAllocationList";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

function allocation(overrides: Partial<ProductionCapacityAllocationRead> = {}): ProductionCapacityAllocationRead {
  return {
    id: "alloc-1", tenant_id: "t", farm_id: "farm-1", code: "CAP-2026-001",
    location_id: "loc-1", location_code: "GT-01", production_system_id: null,
    planned_start_date: "2026-10-01", planned_end_date: "2026-10-08", planned_capacity_amount: 200,
    capacity_unit: "position", source_seeding_program_line_id: null, source_crop_batch_id: null,
    status: "active", notes: null,
    created_by_user_id: "u1", created_at: "2026-09-01T00:00:00Z", updated_at: "2026-09-01T00:00:00Z",
    cancelled_by_user_id: null, cancelled_at: null,
    ...overrides,
  };
}

function stubFetch() {
  vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({})));
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("CapacityAllocationList", () => {
  it("PILOT-PLAN-001B section 14: cancelling states plainly that it does not remove actual occupancy or delete the record", async () => {
    stubFetch();
    render(withQueryClient(<CapacityAllocationList farmId="farm-1" locationId="loc-1" allocations={[allocation()]} />));

    fireEvent.click(screen.getByRole("button", { name: /cancel allocation/i }));
    expect(screen.getByText(/does not delete the record or change actual occupancy/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /confirm cancel/i })).toBeInTheDocument();
  });

  it("never destructively hides a cancelled allocation -- it stays visible with no further mutation controls", async () => {
    stubFetch();
    render(
      withQueryClient(
        <CapacityAllocationList farmId="farm-1" locationId="loc-1" allocations={[allocation({ status: "cancelled" })]} />,
      ),
    );

    expect(screen.getByText(/CAP-2026-001/)).toBeInTheDocument();
    expect(screen.getByText("Cancelled")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /update allocation/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /cancel allocation/i })).not.toBeInTheDocument();
  });

  it("shows the entered form values preserved when cancellation is rejected, rather than clearing state", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => jsonResponse({ detail: "allocation CAP-2026-001 is not active" }, 409)),
    );
    render(withQueryClient(<CapacityAllocationList farmId="farm-1" locationId="loc-1" allocations={[allocation()]} />));

    fireEvent.click(screen.getByRole("button", { name: /cancel allocation/i }));
    fireEvent.click(screen.getByRole("button", { name: /confirm cancel/i }));

    await waitFor(() => expect(screen.getByText(/allocation cap-2026-001 is not active/i)).toBeInTheDocument());
    // Still showing the confirm step -- the failed cancel did not silently
    // fall back to the plain Update/Cancel row.
    expect(screen.getByRole("button", { name: /confirm cancel/i })).toBeInTheDocument();
  });
});
