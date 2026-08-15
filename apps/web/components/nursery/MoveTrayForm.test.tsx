import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { withQueryClient } from "@/lib/test-utils";

import { MoveTrayForm } from "./MoveTrayForm";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const CARRIER_TYPE = { id: "ct-1", code: "seed_tray", name: "Seed Tray" };
const TRAYS = [
  {
    batch_id: "batch-1", batch_code: "CB-0001",
    seed_lot: { id: "lot-1", code: "LOT-01", supplier_lot_reference: null, crop: { id: "c1", code: "ICE", common_name: "Iceberg" }, variety: { id: "v1", code: "MAM", name: "Mamutik" } },
    tray: { id: "tray-1", code: "ST-0001", carrier_type: CARRIER_TYPE },
    batch_carrier_assignment_id: "bca-1", seeds_sown: 200, state: "awaiting_placement", placement: null,
  },
  {
    batch_id: "batch-2", batch_code: "CB-0002",
    seed_lot: { id: "lot-1", code: "LOT-01", supplier_lot_reference: null, crop: { id: "c1", code: "ICE", common_name: "Iceberg" }, variety: { id: "v1", code: "MAM", name: "Mamutik" } },
    tray: { id: "tray-2", code: "ST-0002", carrier_type: CARRIER_TYPE },
    batch_carrier_assignment_id: "bca-2", seeds_sown: 180, state: "in_germination",
    placement: {
      trolley: { id: "trolley-9", code: "GT-09", name: "Trolley 9" },
      chamber: { id: "chamber-9", code: "GC-09", name: "Chamber 9" },
      slot: { id: "slot-9", code: "S01", name: "Slot 1", shelf_code: "L1" },
    },
  },
];
const TROLLEYS = [
  { id: "trolley-1", code: "GT-01", name: "Trolley 1", chamber: { id: "chamber-1", code: "GC-01", name: "Chamber 1" }, total_slot_count: 4, occupied_slot_count: 1, available_slot_count: 3 },
];
const SLOTS = [
  { id: "slot-1", code: "S01", name: "Slot 1", shelf_code: "L1", occupied: false },
  { id: "slot-2", code: "S02", name: "Slot 2", shelf_code: "L1", occupied: true },
  { id: "slot-3", code: "S01", name: "Slot 1", shelf_code: "L2", occupied: false },
];

function stubFetch(overrides: Record<string, unknown> = {}) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/germination/trays")) return jsonResponse(overrides.trays ?? TRAYS);
      if (url.includes("/germination/trolleys/available")) return jsonResponse(overrides.trolleys ?? TROLLEYS);
      if (url.includes("/slots")) return jsonResponse(overrides.slots ?? SLOTS);
      return jsonResponse([]);
    }),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

async function selectTrayTrolleyLevelSlot() {
  await waitFor(() => expect(screen.getByText(/CB-0001 — ST-0001/)).toBeInTheDocument());
  fireEvent.change(screen.getByLabelText(/seed tray/i), { target: { value: "tray-1" } });
  await waitFor(() => expect(screen.getByText(/GT-01 — GC-01/)).toBeInTheDocument());
  fireEvent.change(screen.getByLabelText(/^trolley$/i), { target: { value: "trolley-1" } });
  await waitFor(() => expect(screen.getByText("L1")).toBeInTheDocument());
  fireEvent.change(screen.getByLabelText(/^level$/i), { target: { value: "L1" } });
  await waitFor(() => {
    const select = screen.getByLabelText(/^slot$/i) as HTMLSelectElement;
    expect(select.options.length).toBeGreaterThan(1);
  });
  fireEvent.change(screen.getByLabelText(/^slot$/i), { target: { value: "slot-1" } });
}

describe("MoveTrayForm", () => {
  it("lists only Seed Trays awaiting Germination placement, excluding ones already in Germination", async () => {
    stubFetch();
    render(withQueryClient(<MoveTrayForm farmId="farm-1" onSubmit={vi.fn()} onCancel={vi.fn()} isSubmitting={false} />));
    await waitFor(() => expect(screen.getByText(/CB-0001 — ST-0001/)).toBeInTheDocument());
    expect(screen.queryByText(/CB-0002 — ST-0002/)).not.toBeInTheDocument();
  });

  it("shows a zero-eligible-Tray empty message", async () => {
    stubFetch({ trays: [] });
    render(withQueryClient(<MoveTrayForm farmId="farm-1" onSubmit={vi.fn()} onCancel={vi.fn()} isSubmitting={false} />));
    await waitFor(() =>
      expect(screen.getByText(/no seed trays are awaiting germination placement/i)).toBeInTheDocument(),
    );
  });

  it("shows a zero-eligible-Trolley message when no Trolley is currently in Germination", async () => {
    stubFetch({ trolleys: [] });
    render(withQueryClient(<MoveTrayForm farmId="farm-1" onSubmit={vi.fn()} onCancel={vi.fn()} isSubmitting={false} />));
    await waitFor(() =>
      expect(screen.getByText(/no trolleys are currently placed in a germination chamber/i)).toBeInTheDocument(),
    );
  });

  it("cascades Trolley -> Level -> Slot, only offering unoccupied slots", async () => {
    stubFetch();
    render(withQueryClient(<MoveTrayForm farmId="farm-1" onSubmit={vi.fn()} onCancel={vi.fn()} isSubmitting={false} />));
    await waitFor(() => expect(screen.getByText(/CB-0001 — ST-0001/)).toBeInTheDocument());
    await waitFor(() => expect(screen.getByText(/GT-01 — GC-01/)).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText(/^trolley$/i), { target: { value: "trolley-1" } });
    await waitFor(() => expect(screen.getByText("L1")).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText(/^level$/i), { target: { value: "L1" } });
    await waitFor(() => {
      const select = screen.getByLabelText(/^slot$/i) as HTMLSelectElement;
      expect(select.options.length).toBeGreaterThan(1);
    });
    const slotSelect = screen.getByLabelText(/^slot$/i) as HTMLSelectElement;
    const optionValues = Array.from(slotSelect.options).map((o) => o.value);
    expect(optionValues).toContain("slot-1");
    expect(optionValues).not.toContain("slot-2"); // occupied
  });

  it("shows a full-context review (Batch/Tray/Seeds/Trolley/Chamber/Level/Slot) with no Germination outcome field, then submits", async () => {
    stubFetch();
    const onSubmit = vi.fn();
    render(withQueryClient(<MoveTrayForm farmId="farm-1" onSubmit={onSubmit} onCancel={vi.fn()} isSubmitting={false} />));
    await selectTrayTrolleyLevelSlot();
    fireEvent.click(screen.getByRole("button", { name: "Review" }));

    await waitFor(() => expect(screen.getByText("Review before moving")).toBeInTheDocument());
    expect(screen.getByText("CB-0001")).toBeInTheDocument();
    expect(screen.getByText("ST-0001")).toBeInTheDocument();
    expect(screen.getByText("200")).toBeInTheDocument();
    expect(screen.getByText("GT-01")).toBeInTheDocument();
    expect(screen.getByText("GC-01")).toBeInTheDocument();
    expect(screen.getByText("L1")).toBeInTheDocument();
    expect(screen.getByText("S01")).toBeInTheDocument();
    expect(screen.queryByText(/germination (check|percentage|rate|outcome)/i)).not.toBeInTheDocument();
    expect(onSubmit).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Move to Germination" }));
    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
    const payload = onSubmit.mock.calls[0][0];
    expect(payload.tray_id).toBe("tray-1");
    expect(payload.trolley_id).toBe("trolley-1");
    expect(payload.slot_id).toBe("slot-1");
  });

  it("shows a server error when the Trolley is rejected as not currently in Germination", async () => {
    stubFetch();
    render(
      withQueryClient(
        <MoveTrayForm
          farmId="farm-1" onSubmit={vi.fn()} onCancel={vi.fn()} isSubmitting={false}
          serverError="Trolley GT-01 is not placed in a Germination Chamber."
        />,
      ),
    );
    await selectTrayTrolleyLevelSlot();
    fireEvent.click(screen.getByRole("button", { name: "Review" }));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(/not placed in a germination chamber/i));
  });

  it("calls onCancel without submitting", async () => {
    stubFetch();
    const onSubmit = vi.fn();
    const onCancel = vi.fn();
    render(withQueryClient(<MoveTrayForm farmId="farm-1" onSubmit={onSubmit} onCancel={onCancel} isSubmitting={false} />));
    await waitFor(() => expect(screen.getByText(/CB-0001 — ST-0001/)).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onCancel).toHaveBeenCalledTimes(1);
    expect(onSubmit).not.toHaveBeenCalled();
  });
});
