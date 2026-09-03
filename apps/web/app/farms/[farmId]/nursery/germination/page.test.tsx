import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useParams: () => ({ farmId: "farm-1" }),
}));

import { withQueryClient } from "@/lib/test-utils";

import GerminationPage from "./page";

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
      position: { id: "slot-9", code: "S01", name: "Slot 1", level_code: "GT-09-L01", mode: "legacy" },
    },
  },
];

function stubFetch(overrides: Record<string, unknown> = {}) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/germination/trays")) return jsonResponse(overrides.trays ?? TRAYS);
      if (url.includes("/germination/chambers/available")) return jsonResponse(overrides.chambers ?? []);
      if (url.includes("/germination/trolleys/available")) return jsonResponse(overrides.trolleys ?? []);
      if (url.includes("/germination-outcomes/current")) {
        return jsonResponse(
          overrides.currentOutcomes ?? {
            batch_id: "batch-1", batch_code: "CB-0001", trays: [], authoritative_living_seedling_total: 0,
            completed_tray_count: 0, unresolved_tray_count: 0, all_resolved: false,
          },
        );
      }
      if (url.includes("/assets")) return jsonResponse(overrides.assets ?? []);
      if (url.includes("/nursery/seedling/trays")) return jsonResponse(overrides.seedlingTrays ?? []);
      if (url.includes("/nursery/seedling/tables/available")) return jsonResponse(overrides.seedlingTables ?? []);
      return jsonResponse([]);
    }),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("GerminationPage", () => {
  it("shows an empty state when there are no Sown Seed Trays yet", async () => {
    stubFetch({ trays: [] });
    render(withQueryClient(<GerminationPage />));
    await waitFor(() => expect(screen.getByText("No Sown Seed Trays yet")).toBeInTheDocument());
  });

  it("renders the awaiting-placement and already-in-Germination states with human-readable codes, no raw UUIDs", async () => {
    stubFetch();
    render(withQueryClient(<GerminationPage />));
    await waitFor(() => expect(screen.getByText("CB-0001")).toBeInTheDocument());
    expect(screen.getByText("Awaiting placement")).toBeInTheDocument();
    expect(screen.getByText("In Germination")).toBeInTheDocument();
    expect(screen.getByText("GT-09 / GC-09 / S01")).toBeInTheDocument();
    expect(screen.queryByText(/trolley-9|chamber-9|slot-9|batch-1|batch-2/)).not.toBeInTheDocument();
  });

  it("never shows biological Germination outcome fields on the read view", async () => {
    stubFetch();
    render(withQueryClient(<GerminationPage />));
    await waitFor(() => expect(screen.getByText("CB-0001")).toBeInTheDocument());
    expect(screen.queryByText(/germination (check|percentage|rate|outcome)/i)).not.toBeInTheDocument();
  });

  it("opens the Place Trolley form and returns to the list on cancel", async () => {
    stubFetch();
    render(withQueryClient(<GerminationPage />));
    await waitFor(() => expect(screen.getByText("CB-0001")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Place Trolley" }));
    await waitFor(() => expect(screen.getByLabelText(/^trolley$/i)).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.getByText("CB-0001")).toBeInTheDocument());
  });

  it("opens the Move Tray form and returns to the list on cancel", async () => {
    stubFetch();
    render(withQueryClient(<GerminationPage />));
    await waitFor(() => expect(screen.getByText("CB-0001")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Move Tray to Germination" }));
    await waitFor(() => expect(screen.getByText(/CB-0001 — ST-0001/)).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.getByText("Place Trolley")).toBeInTheDocument());
  });

  it("opens the Record Outcome form and returns to the list on cancel", async () => {
    stubFetch();
    render(withQueryClient(<GerminationPage />));
    await waitFor(() => expect(screen.getByText("CB-0001")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Record Outcome" }));
    await waitFor(() => expect(screen.getByText(/CB-0001 — ST-0001/)).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.getByText("Place Trolley")).toBeInTheDocument());
  });

  it("opens the Move to Seedling form and returns to the list on cancel", async () => {
    stubFetch({
      seedlingTrays: [
        {
          batch_id: "batch-1", batch_code: "CB-0001",
          seed_lot: { id: "lot-1", code: "LOT-01", supplier_lot_reference: null, crop: { id: "c1", code: "ICE", common_name: "Iceberg" }, variety: { id: "v1", code: "MAM", name: "Mamutik" } },
          tray: { id: "tray-1", code: "ST-0001", carrier_type: CARRIER_TYPE },
          batch_carrier_assignment_id: "bca-1", seeds_sown: 200,
          germination_handoff: { normal_seedling_count: 190, abnormal_seedling_count: 6, living_seedling_count: 196, effective_time: "2026-08-01T00:00:00Z" },
          seedling_entry: null,
          current_placement: { kind: "in_germination", germination: null, seedling_table: null },
          state: "ready_for_seedling",
        },
      ],
    });
    render(withQueryClient(<GerminationPage />));
    await waitFor(() => expect(screen.getByText("CB-0001")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Move to Seedling" }));
    await waitFor(() => expect(screen.getByText(/CB-0001 — ST-0001/)).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.getByText("Place Trolley")).toBeInTheDocument());
  });
});
