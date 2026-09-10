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
      position: { id: "level-9", code: "GT-09-L01", name: "Level GT-09-L01", level_code: "GT-09-L01", mode: "direct" },
    },
  },
];
const MULTI_BATCH_TRAYS = [
  TRAYS[0],
  {
    batch_id: "batch-1", batch_code: "CB-0001",
    seed_lot: { id: "lot-1", code: "LOT-01", supplier_lot_reference: null, crop: { id: "c1", code: "ICE", common_name: "Iceberg" }, variety: { id: "v1", code: "MAM", name: "Mamutik" } },
    tray: { id: "tray-1b", code: "ST-0003", carrier_type: CARRIER_TYPE },
    batch_carrier_assignment_id: "bca-3", seeds_sown: 200, state: "awaiting_placement", placement: null,
  },
];
const TROLLEYS = [
  {
    id: "trolley-1", code: "GT-01", name: "Trolley 1", chamber: { id: "chamber-1", code: "GC-01", name: "Chamber 1" },
    total_capacity: 6, occupied_count: 1, available_capacity: 5,
  },
];
const LEVELS = [
  {
    id: "level-1", code: "GT-01-L01", name: "Level GT-01-L01", mode: "direct",
    capacity: 4, occupied_count: 1, available_capacity: 3, slots: [],
  },
  {
    id: "level-2", code: "GT-01-L02", name: "Level GT-01-L02", mode: "direct",
    capacity: 2, occupied_count: 2, available_capacity: 0, slots: [],
  },
  {
    id: "level-3", code: "GT-01-L03", name: "Level GT-01-L03", mode: "legacy",
    capacity: null, occupied_count: 1, available_capacity: 1,
    slots: [
      { id: "slot-1", code: "S01", name: "Slot 1", occupied: false },
      { id: "slot-2", code: "S02", name: "Slot 2", occupied: true },
    ],
  },
  {
    id: "level-4", code: "GT-01-L04", name: "Level GT-01-L04", mode: "invalid",
    capacity: null, occupied_count: 0, available_capacity: null, slots: [],
  },
];

function stubFetch(overrides: Record<string, unknown> = {}) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/germination/trays")) return jsonResponse(overrides.trays ?? TRAYS);
      if (url.includes("/germination/trolleys/available")) return jsonResponse(overrides.trolleys ?? TROLLEYS);
      if (url.includes("/levels")) return jsonResponse(overrides.levels ?? LEVELS);
      return jsonResponse([]);
    }),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

async function selectTrayAndTrolley() {
  await waitFor(() => expect(screen.getByText(/CB-0001 — ST-0001/)).toBeInTheDocument());
  fireEvent.change(screen.getByLabelText(/seed tray/i), { target: { value: "tray-1" } });
  await waitFor(() => expect(screen.getByText(/GT-01 — GC-01/)).toBeInTheDocument());
  fireEvent.change(screen.getByLabelText(/^trolley$/i), { target: { value: "trolley-1" } });
  await waitFor(() => expect(screen.getByText(/GT-01-L01/)).toBeInTheDocument());
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

  it("treats a direct Level as terminal -- no Slot selector, submits the Level's own id", async () => {
    stubFetch();
    const onSubmit = vi.fn();
    render(withQueryClient(<MoveTrayForm farmId="farm-1" onSubmit={onSubmit} onCancel={vi.fn()} isSubmitting={false} />));
    await selectTrayAndTrolley();
    fireEvent.change(screen.getByLabelText(/^level$/i), { target: { value: "level-1" } });

    expect(screen.queryByLabelText(/^slot$/i)).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Review" }));
    await waitFor(() => expect(screen.getByText("Review before moving")).toBeInTheDocument());
    expect(screen.getByText("GT-01-L01")).toBeInTheDocument();
    expect(screen.queryByText("Slot")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Move to Germination" }));
    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
    const payload = onSubmit.mock.calls[0][0];
    expect(payload.tray_id).toBe("tray-1");
    expect(payload.trolley_id).toBe("trolley-1");
    expect(payload.asset_position_id).toBe("level-1");
  });

  it("shows a full direct Level as disabled, never selectable", async () => {
    stubFetch();
    render(withQueryClient(<MoveTrayForm farmId="farm-1" onSubmit={vi.fn()} onCancel={vi.fn()} isSubmitting={false} />));
    await selectTrayAndTrolley();

    const levelSelect = screen.getByLabelText(/^level$/i) as HTMLSelectElement;
    const fullOption = Array.from(levelSelect.options).find((o) => o.value === "level-2")!;
    expect(fullOption.disabled).toBe(true);
    expect(fullOption.textContent).toMatch(/full/i);
  });

  it("cascades Trolley -> Level -> Slot for a legacy Level, only offering unoccupied slots", async () => {
    stubFetch();
    render(withQueryClient(<MoveTrayForm farmId="farm-1" onSubmit={vi.fn()} onCancel={vi.fn()} isSubmitting={false} />));
    await selectTrayAndTrolley();
    fireEvent.change(screen.getByLabelText(/^level$/i), { target: { value: "level-3" } });
    await waitFor(() => expect(screen.getByLabelText(/^slot$/i)).toBeInTheDocument());

    const slotSelect = screen.getByLabelText(/^slot$/i) as HTMLSelectElement;
    const optionValues = Array.from(slotSelect.options).map((o) => o.value);
    expect(optionValues).toContain("slot-1");
    expect(optionValues).not.toContain("slot-2"); // occupied
  });

  it("shows a full-context legacy review (Batch/Tray/Seeds/Trolley/Chamber/Level/Slot) with no Germination outcome field, then submits", async () => {
    stubFetch();
    const onSubmit = vi.fn();
    render(withQueryClient(<MoveTrayForm farmId="farm-1" onSubmit={onSubmit} onCancel={vi.fn()} isSubmitting={false} />));
    await selectTrayAndTrolley();
    fireEvent.change(screen.getByLabelText(/^level$/i), { target: { value: "level-3" } });
    await waitFor(() => expect(screen.getByLabelText(/^slot$/i)).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText(/^slot$/i), { target: { value: "slot-1" } });
    fireEvent.click(screen.getByRole("button", { name: "Review" }));

    await waitFor(() => expect(screen.getByText("Review before moving")).toBeInTheDocument());
    expect(screen.getByText("CB-0001")).toBeInTheDocument();
    expect(screen.getByText("ST-0001")).toBeInTheDocument();
    expect(screen.getByText("200")).toBeInTheDocument();
    expect(screen.getByText("GT-01")).toBeInTheDocument();
    expect(screen.getByText("GC-01")).toBeInTheDocument();
    expect(screen.getByText("GT-01-L03")).toBeInTheDocument();
    expect(screen.getByText("S01")).toBeInTheDocument();
    expect(screen.queryByText(/germination (check|percentage|rate|outcome)/i)).not.toBeInTheDocument();
    expect(onSubmit).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Move to Germination" }));
    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
    const payload = onSubmit.mock.calls[0][0];
    expect(payload.tray_id).toBe("tray-1");
    expect(payload.trolley_id).toBe("trolley-1");
    expect(payload.asset_position_id).toBe("slot-1");
  });

  it("shows an invalid Level as disabled with a configuration-problem label, never selectable", async () => {
    stubFetch();
    render(withQueryClient(<MoveTrayForm farmId="farm-1" onSubmit={vi.fn()} onCancel={vi.fn()} isSubmitting={false} />));
    await selectTrayAndTrolley();

    const levelSelect = screen.getByLabelText(/^level$/i) as HTMLSelectElement;
    const invalidOption = Array.from(levelSelect.options).find((o) => o.value === "level-4")!;
    expect(invalidOption.disabled).toBe(true);
    expect(invalidOption.textContent).toMatch(/not configured/i);
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
    await selectTrayAndTrolley();
    fireEvent.change(screen.getByLabelText(/^level$/i), { target: { value: "level-1" } });
    fireEvent.click(screen.getByRole("button", { name: "Review" }));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(/not placed in a germination chamber/i));
  });

  it("PILOT-UX-001: auto-selects the incoming Batch's Seed Tray when exactly one is eligible", async () => {
    stubFetch();
    render(
      withQueryClient(
        <MoveTrayForm farmId="farm-1" onSubmit={vi.fn()} onCancel={vi.fn()} isSubmitting={false} initialBatchId="batch-1" />,
      ),
    );
    await waitFor(() => expect(screen.getByText(/continuing from sowing/i)).toBeInTheDocument());
    const traySelect = screen.getByLabelText(/seed tray/i) as HTMLSelectElement;
    await waitFor(() => expect(traySelect.value).toBe("tray-1"));
  });

  it("PILOT-UX-001: offers a Place Trolley action from the empty Trolley state instead of a dead end", async () => {
    stubFetch({ trolleys: [] });
    const onSetUpTrolley = vi.fn();
    render(
      withQueryClient(
        <MoveTrayForm
          farmId="farm-1" onSubmit={vi.fn()} onCancel={vi.fn()} isSubmitting={false} onSetUpTrolley={onSetUpTrolley}
        />,
      ),
    );
    await waitFor(() => expect(screen.getByText("No Germination Trolley placed")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Place Trolley" }));
    expect(onSetUpTrolley).toHaveBeenCalledTimes(1);
  });

  it("PILOT-UX-001: shows a compact bulk board (trays collapsed by default) and completes one row move via 'Show trays', without a separate review step", async () => {
    stubFetch({ trays: MULTI_BATCH_TRAYS });
    const onSubmitOne = vi.fn().mockResolvedValue({});
    render(
      withQueryClient(
        <MoveTrayForm
          farmId="farm-1" onSubmit={vi.fn()} onCancel={vi.fn()} isSubmitting={false}
          initialBatchId="batch-1" onSubmitOne={onSubmitOne}
        />,
      ),
    );
    await waitFor(() =>
      expect(screen.getByText(/continuing from sowing — batch cb-0001, 2 eligible seed trays/i)).toBeInTheDocument(),
    );
    expect(screen.getByText("2 trays ready")).toBeInTheDocument();
    // Individual tray rows stay collapsed by default.
    expect(screen.queryByText("ST-0001")).not.toBeInTheDocument();
    // No per-tray picker, no Batch re-selection -- destination is chosen once.
    expect(screen.queryByLabelText(/^seed tray$/i)).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Show trays" }));
    expect(screen.getByText("ST-0001")).toBeInTheDocument();
    expect(screen.getByText("ST-0003")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText(/^trolley$/i), { target: { value: "trolley-1" } });
    await waitFor(() => expect(screen.getByText(/GT-01-L01/)).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText(/^level$/i), { target: { value: "level-1" } });

    fireEvent.click(screen.getAllByRole("button", { name: "Move" })[0]);
    await waitFor(() => expect(onSubmitOne).toHaveBeenCalledTimes(1));
    const payload = onSubmitOne.mock.calls[0][0];
    expect(payload.tray_id).toBe("tray-1");
    expect(payload.trolley_id).toBe("trolley-1");
    expect(payload.asset_position_id).toBe("level-1");
    // The destination stays selected -- ready to move the next tray immediately.
    expect((screen.getByLabelText(/^trolley$/i) as HTMLSelectElement).value).toBe("trolley-1");
    expect(screen.queryByText("Review before moving")).not.toBeInTheDocument();
  });

  it("PILOT-UX-001: Move All invokes the existing single-tray operation for every eligible tray and reports success", async () => {
    stubFetch({ trays: MULTI_BATCH_TRAYS });
    const onSubmitOne = vi.fn().mockResolvedValue({});
    render(
      withQueryClient(
        <MoveTrayForm
          farmId="farm-1" onSubmit={vi.fn()} onCancel={vi.fn()} isSubmitting={false}
          initialBatchId="batch-1" onSubmitOne={onSubmitOne}
        />,
      ),
    );
    await waitFor(() => expect(screen.getByText("2 trays ready")).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText(/^trolley$/i), { target: { value: "trolley-1" } });
    await waitFor(() => expect(screen.getByText(/GT-01-L01/)).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText(/^level$/i), { target: { value: "level-1" } });

    fireEvent.click(screen.getByRole("button", { name: "Move All 2 Trays" }));

    await waitFor(() => expect(onSubmitOne).toHaveBeenCalledTimes(2));
    expect(onSubmitOne.mock.calls[0][0]).toMatchObject({ tray_id: "tray-1", trolley_id: "trolley-1", asset_position_id: "level-1" });
    expect(onSubmitOne.mock.calls[1][0]).toMatchObject({ tray_id: "tray-1b", trolley_id: "trolley-1", asset_position_id: "level-1" });
    // Each call is independently idempotent.
    expect(onSubmitOne.mock.calls[0][0].client_command_id).not.toBe(onSubmitOne.mock.calls[1][0].client_command_id);
    await waitFor(() => expect(screen.getByText(/2 trays moved to Trolley GT-01 \/ Level GT-01-L01/i)).toBeInTheDocument());
  });

  it("PILOT-UX-001: Move All stops at the first failure and reports truthful partial completion, never pretending a rollback", async () => {
    stubFetch({ trays: MULTI_BATCH_TRAYS });
    const onSubmitOne = vi.fn().mockResolvedValueOnce({}).mockRejectedValueOnce(new Error("Level is full"));
    render(
      withQueryClient(
        <MoveTrayForm
          farmId="farm-1" onSubmit={vi.fn()} onCancel={vi.fn()} isSubmitting={false}
          initialBatchId="batch-1" onSubmitOne={onSubmitOne}
        />,
      ),
    );
    await waitFor(() => expect(screen.getByText("2 trays ready")).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText(/^trolley$/i), { target: { value: "trolley-1" } });
    await waitFor(() => expect(screen.getByText(/GT-01-L01/)).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText(/^level$/i), { target: { value: "level-1" } });

    fireEvent.click(screen.getByRole("button", { name: "Move All 2 Trays" }));

    await waitFor(() => expect(onSubmitOne).toHaveBeenCalledTimes(2));
    expect(screen.getByText("1 tray moved successfully")).toBeInTheDocument();
    expect(screen.getByText("1 tray remains")).toBeInTheDocument();
    expect(screen.getByText(/tray st-0003 could not be moved/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Continue Remaining" })).toBeInTheDocument();
  });

  it("PILOT-UX-001: excludes slot-based legacy Levels from the Move All destination", async () => {
    stubFetch({ trays: MULTI_BATCH_TRAYS });
    render(
      withQueryClient(
        <MoveTrayForm
          farmId="farm-1" onSubmit={vi.fn()} onCancel={vi.fn()} isSubmitting={false}
          initialBatchId="batch-1" onSubmitOne={vi.fn()}
        />,
      ),
    );
    await waitFor(() => expect(screen.getByText("2 trays ready")).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText(/^trolley$/i), { target: { value: "trolley-1" } });
    await waitFor(() => expect(screen.getByText(/GT-01-L03/)).toBeInTheDocument());

    const levelSelect = screen.getByLabelText(/^level$/i) as HTMLSelectElement;
    const legacyOption = Array.from(levelSelect.options).find((o) => o.value === "level-3")!;
    expect(legacyOption.disabled).toBe(true);
    expect(legacyOption.textContent).toMatch(/needs individual placement/i);
  });

  it("PILOT-UX-001: falls back to the single-tray flow for a multi-tray Batch when no bulk submit handler is supplied", async () => {
    stubFetch({ trays: MULTI_BATCH_TRAYS });
    render(
      withQueryClient(
        <MoveTrayForm farmId="farm-1" onSubmit={vi.fn()} onCancel={vi.fn()} isSubmitting={false} initialBatchId="batch-1" />,
      ),
    );
    await waitFor(() => expect(screen.getByLabelText(/^seed tray$/i)).toBeInTheDocument());
    expect(screen.queryByText(/eligible seed trays/i)).not.toBeInTheDocument();
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
