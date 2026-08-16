import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useParams: () => ({ farmId: "farm-1" }),
}));

import { withQueryClient } from "@/lib/test-utils";

import SeedlingPage from "./page";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const REASONS = [
  { code: "WEAK_SEEDLING", name: "Weak seedling" },
  { code: "DISEASE", name: "Disease" },
];

const TRAYS = [
  {
    batch_id: "batch-1", batch_code: "CB-0001", tray_id: "tray-1", tray_code: "ST-0001",
    crop_common_name: "Iceberg", variety_name: "Mamutik", seed_lot_code: "LOT-01",
    batch_carrier_assignment_id: "bca-1", seedling_entry_id: "se-1",
    starting_living_seedling_count: 196, total_reduction_magnitude: 4, total_reversal_magnitude: 0,
    current_living_seedling_count: 192, is_depleted: false, event_count: 1,
    seedling_table_id: "table-1", seedling_table_code: "ST01",
    assignment_active: true, assignment_released_effective_time: null,
  },
  {
    batch_id: "batch-2", batch_code: "CB-0002", tray_id: "tray-2", tray_code: "ST-0002",
    crop_common_name: "Iceberg", variety_name: "Mamutik", seed_lot_code: "LOT-01",
    batch_carrier_assignment_id: "bca-2", seedling_entry_id: "se-2",
    starting_living_seedling_count: 190, total_reduction_magnitude: 0, total_reversal_magnitude: 0,
    current_living_seedling_count: 190, is_depleted: false, event_count: 0,
    seedling_table_id: "table-2", seedling_table_code: "ST02",
    assignment_active: true, assignment_released_effective_time: null,
  },
];

const HISTORY = {
  seedling_entry_id: "se-1", starting_living_seedling_count: 196, current_living_seedling_count: 192,
  events: [
    {
      id: "evt-1", command_id: "cmd-1", seedling_entry_id: "se-1", event_kind: "REDUCTION",
      reason_code: "WEAK_SEEDLING", quantity_delta: -4, effective_time: "2026-08-10T09:00:00Z",
      note: null, reverses_event_id: null, corrects_event_id: null, actor_user_id: "user-1",
      recorded_at: "2026-08-10T09:00:01Z",
    },
  ],
};

function stubFetch(overrides: Record<string, unknown> = {}) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/nursery/seedling/biological-trays")) return jsonResponse(overrides.trays ?? TRAYS);
      if (url.includes("/nursery/seedling/disposition-reasons")) return jsonResponse(overrides.reasons ?? REASONS);
      if (url.includes("/nursery/seedling/dispositions?")) return jsonResponse(overrides.history ?? HISTORY);
      return jsonResponse([]);
    }),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("SeedlingPage", () => {
  it("shows an empty state when there are no Seedling Trays yet", async () => {
    stubFetch({ trays: [] });
    render(withQueryClient(<SeedlingPage />));
    await waitFor(() => expect(screen.getByText("No Seedling Trays yet")).toBeInTheDocument());
  });

  it("lists Trays with starting/current counts and a status badge, no raw UUIDs", async () => {
    stubFetch();
    render(withQueryClient(<SeedlingPage />));
    await waitFor(() => expect(screen.getByText("CB-0001")).toBeInTheDocument());
    expect(screen.getByText("196")).toBeInTheDocument();
    expect(screen.getByText("192")).toBeInTheDocument();
    expect(screen.getAllByText("Active").length).toBeGreaterThan(0);
    expect(screen.queryByText(/bca-1|tray-1|se-1/)).not.toBeInTheDocument();
  });

  it("opens the Record disposition form from the header action and returns to the list on cancel", async () => {
    stubFetch();
    render(withQueryClient(<SeedlingPage />));
    await waitFor(() => expect(screen.getByText("CB-0001")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Record biological disposition" }));
    await waitFor(() => expect(screen.getByText(/CB-0001 — ST-0001/)).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.getByText("Record biological disposition")).toBeInTheDocument());
  });

  it("opens the Record form preselected to a row's Tray", async () => {
    stubFetch();
    render(withQueryClient(<SeedlingPage />));
    await waitFor(() => expect(screen.getByText("CB-0001")).toBeInTheDocument());
    const recordButtons = screen.getAllByRole("button", { name: "Record" });
    fireEvent.click(recordButtons[0]);
    await waitFor(() => expect(screen.getByText(/CB-0001 — ST-0001/)).toBeInTheDocument());
    expect(screen.getByLabelText(/seed tray/i)).toBeDisabled();
  });

  it("opens History for a row with recorded events and shows the un-collapsed event list", async () => {
    stubFetch();
    render(withQueryClient(<SeedlingPage />));
    await waitFor(() => expect(screen.getByText("CB-0001")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "History" }));
    await waitFor(() => expect(screen.getByText("Recorded")).toBeInTheDocument());
    expect(screen.getByText("WEAK_SEEDLING")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    await waitFor(() => expect(screen.getByText("Record biological disposition")).toBeInTheDocument());
  });

  it("never offers History for a Tray with no recorded events", async () => {
    stubFetch();
    render(withQueryClient(<SeedlingPage />));
    await waitFor(() => expect(screen.getByText("CB-0002")).toBeInTheDocument());
    expect(screen.getAllByRole("button", { name: "History" })).toHaveLength(1);
  });
});
