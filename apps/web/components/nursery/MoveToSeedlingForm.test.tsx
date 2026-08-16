import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { withQueryClient } from "@/lib/test-utils";

import { MoveToSeedlingForm } from "./MoveToSeedlingForm";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const CARRIER_TYPE = { id: "ct-1", code: "seed_tray", name: "Seed Tray" };
const SEED_LOT = {
  id: "lot-1", code: "LOT-01", supplier_lot_reference: null,
  crop: { id: "c1", code: "ICE", common_name: "Iceberg" }, variety: { id: "v1", code: "MAM", name: "Mamutik" },
};

const TRAYS = [
  {
    batch_id: "batch-1", batch_code: "CB-0001", seed_lot: SEED_LOT,
    tray: { id: "tray-1", code: "ST-0001", carrier_type: CARRIER_TYPE },
    batch_carrier_assignment_id: "bca-1", seeds_sown: 200,
    germination_handoff: { normal_seedling_count: 190, abnormal_seedling_count: 6, living_seedling_count: 196, effective_time: "2026-08-01T00:00:00Z" },
    seedling_entry: null,
    current_placement: { kind: "in_germination", germination: null, seedling_table: null },
    state: "ready_for_seedling",
  },
  {
    batch_id: "batch-2", batch_code: "CB-0002", seed_lot: SEED_LOT,
    tray: { id: "tray-2", code: "ST-0002", carrier_type: CARRIER_TYPE },
    batch_carrier_assignment_id: "bca-2", seeds_sown: 180,
    germination_handoff: null, seedling_entry: null,
    current_placement: { kind: "in_germination", germination: null, seedling_table: null },
    state: "no_completed_handoff",
  },
  {
    batch_id: "batch-3", batch_code: "CB-0003", seed_lot: SEED_LOT,
    tray: { id: "tray-3", code: "ST-0003", carrier_type: CARRIER_TYPE },
    batch_carrier_assignment_id: "bca-3", seeds_sown: 200,
    germination_handoff: { normal_seedling_count: 180, abnormal_seedling_count: 10, living_seedling_count: 190, effective_time: "2026-08-01T00:00:00Z" },
    seedling_entry: { id: "se-1", movement_id: "mv-1", source_germination_outcome_snapshot_id: "gos-1", starting_living_seedling_count: 190, effective_time: "2026-08-02T00:00:00Z" },
    current_placement: { kind: "on_seedling_table", germination: null, seedling_table: { id: "table-9", code: "ST09", name: "Table 9" } },
    state: "in_seedling",
  },
];

const TABLES = [
  { id: "table-1", code: "ST01", name: "Table 1", capacity: 4, active_tray_count: 1, remaining_capacity: 3, seedling_area: { id: "area-1", code: "SA", name: "Seedling Area" }, greenhouse: { id: "gh-1", code: "NUR", name: "Nursery" } },
  { id: "table-2", code: "ST02", name: "Table 2", capacity: 1, active_tray_count: 1, remaining_capacity: 0, seedling_area: { id: "area-1", code: "SA", name: "Seedling Area" }, greenhouse: { id: "gh-1", code: "NUR", name: "Nursery" } },
];

function stubFetch(overrides: Record<string, unknown> = {}) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/nursery/seedling/trays")) return jsonResponse(overrides.trays ?? TRAYS);
      if (url.includes("/nursery/seedling/tables/available")) return jsonResponse(overrides.tables ?? TABLES);
      return jsonResponse([]);
    }),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

async function selectTrayAndTable() {
  await waitFor(() => expect(screen.getByText(/CB-0001 — ST-0001/)).toBeInTheDocument());
  fireEvent.change(screen.getByLabelText(/seed tray/i), { target: { value: "bca-1" } });
  await waitFor(() => expect(screen.getByText(/ST01 — Seedling Area/)).toBeInTheDocument());
  fireEvent.change(screen.getByLabelText(/seedling table/i), { target: { value: "table-1" } });
}

describe("MoveToSeedlingForm", () => {
  it("lists only Trays ready for Seedling, excluding no-handoff and already-entered Trays", async () => {
    stubFetch();
    render(withQueryClient(<MoveToSeedlingForm farmId="farm-1" onSubmit={vi.fn()} onCancel={vi.fn()} isSubmitting={false} />));
    await waitFor(() => expect(screen.getByText(/CB-0001 — ST-0001/)).toBeInTheDocument());
    expect(screen.queryByText(/CB-0002 — ST-0002/)).not.toBeInTheDocument();
    expect(screen.queryByText(/CB-0003 — ST-0003/)).not.toBeInTheDocument();
  });

  it("shows an actionable message when no Tray is ready for Seedling", async () => {
    stubFetch({ trays: [] });
    render(withQueryClient(<MoveToSeedlingForm farmId="farm-1" onSubmit={vi.fn()} onCancel={vi.fn()} isSubmitting={false} />));
    await waitFor(() =>
      expect(screen.getByText(/complete the germination assessment first/i)).toBeInTheDocument(),
    );
  });

  it("excludes Seedling Tables with zero remaining capacity", async () => {
    stubFetch();
    render(withQueryClient(<MoveToSeedlingForm farmId="farm-1" onSubmit={vi.fn()} onCancel={vi.fn()} isSubmitting={false} />));
    await waitFor(() => expect(screen.getByText(/CB-0001 — ST-0001/)).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText(/seed tray/i), { target: { value: "bca-1" } });
    await waitFor(() => expect(screen.getByText(/ST01 — Seedling Area/)).toBeInTheDocument());
    expect(screen.queryByText(/ST02 — Seedling Area/)).not.toBeInTheDocument();
  });

  it("shows the completed Germination handoff quantity for the selected Tray", async () => {
    stubFetch();
    render(withQueryClient(<MoveToSeedlingForm farmId="farm-1" onSubmit={vi.fn()} onCancel={vi.fn()} isSubmitting={false} />));
    await waitFor(() => expect(screen.getByText(/CB-0001 — ST-0001/)).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText(/seed tray/i), { target: { value: "bca-1" } });
    await waitFor(() => expect(screen.getByText("196")).toBeInTheDocument());
  });

  it("shows a full review with the establishing-quantity sentence, then submits with no raw UUIDs, loss, or transplant fields", async () => {
    stubFetch();
    const onSubmit = vi.fn();
    render(withQueryClient(<MoveToSeedlingForm farmId="farm-1" onSubmit={onSubmit} onCancel={vi.fn()} isSubmitting={false} />));
    await selectTrayAndTable();
    fireEvent.click(screen.getByRole("button", { name: "Review" }));

    await waitFor(() => expect(screen.getByText("Review before moving to Seedling")).toBeInTheDocument());
    expect(screen.getByText(/this entry will establish 196 living seedlings/i)).toBeInTheDocument();
    expect(screen.getByText("CB-0001")).toBeInTheDocument();
    expect(screen.getByText("ST-0001")).toBeInTheDocument();
    expect(screen.getByText("ST01")).toBeInTheDocument();
    expect(screen.queryByText(/bca-1|tray-1|table-1|gos-1/)).not.toBeInTheDocument();
    expect(screen.queryByText(/loss|removal|weak seedling|disease|reject/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/transplant|cultivation plate|grow cube/i)).not.toBeInTheDocument();
    expect(onSubmit).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Move to Seedling" }));
    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
    const payload = onSubmit.mock.calls[0][0];
    expect(payload.batch_carrier_assignment_id).toBe("bca-1");
    expect(payload.destination_seedling_table_id).toBe("table-1");
    expect(payload).not.toHaveProperty("starting_living_seedling_count");
    expect(payload).not.toHaveProperty("source_germination_outcome_snapshot_id");
  });

  it("shows a server error (e.g. Table became full)", async () => {
    stubFetch();
    render(
      withQueryClient(
        <MoveToSeedlingForm
          farmId="farm-1" onSubmit={vi.fn()} onCancel={vi.fn()} isSubmitting={false}
          serverError="Table ST01 is already occupied at capacity."
        />,
      ),
    );
    await selectTrayAndTable();
    fireEvent.click(screen.getByRole("button", { name: "Review" }));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(/already occupied at capacity/i));
  });

  it("calls onCancel without submitting", async () => {
    stubFetch();
    const onSubmit = vi.fn();
    const onCancel = vi.fn();
    render(withQueryClient(<MoveToSeedlingForm farmId="farm-1" onSubmit={onSubmit} onCancel={onCancel} isSubmitting={false} />));
    await waitFor(() => expect(screen.getByText(/CB-0001 — ST-0001/)).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onCancel).toHaveBeenCalledTimes(1);
    expect(onSubmit).not.toHaveBeenCalled();
  });
});
