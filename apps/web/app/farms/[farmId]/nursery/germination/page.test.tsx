import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const searchParams = new URLSearchParams();

vi.mock("next/navigation", () => ({
  useParams: () => ({ farmId: "farm-1" }),
  useSearchParams: () => searchParams,
}));

import { withQueryClient } from "@/lib/test-utils";

import GerminationPage from "./page";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const CARRIER_TYPE = { id: "ct-1", code: "seed_tray", name: "Seed Tray" };
const SEED_LOT = {
  id: "lot-1", code: "LOT-01", supplier_lot_reference: null,
  crop: { id: "c1", code: "ICE", common_name: "Iceberg" }, variety: { id: "v1", code: "MAM", name: "Mamutik" },
};

// Row A (bca-1): not yet placed -> "Move to Germination".
// Row B (bca-2): placed, never observed -> "Record outcome".
// Row C (bca-3): placed, final outcome recorded, ready for Seedling -> "Move to Seedling".
// Row D (bca-4): already moved on to Seedling -> no truthful next action ("—"), never fabricated.
const TRAYS = [
  {
    batch_id: "batch-1", batch_code: "CB-0001", seed_lot: SEED_LOT,
    tray: { id: "tray-1", code: "ST-0001", carrier_type: CARRIER_TYPE },
    batch_carrier_assignment_id: "bca-1", seeds_sown: 200, state: "awaiting_placement", placement: null,
  },
  {
    batch_id: "batch-2", batch_code: "CB-0002", seed_lot: SEED_LOT,
    tray: { id: "tray-2", code: "ST-0002", carrier_type: CARRIER_TYPE },
    batch_carrier_assignment_id: "bca-2", seeds_sown: 180, state: "in_germination",
    placement: {
      trolley: { id: "t9", code: "GT-09", name: "Trolley 9" },
      chamber: { id: "c9", code: "GC-09", name: "Chamber 9" },
      position: { id: "s9", code: "S01", name: "Slot", level_code: "GT-09-L01", mode: "legacy" },
    },
  },
  {
    batch_id: "batch-3", batch_code: "CB-0003", seed_lot: SEED_LOT,
    tray: { id: "tray-3", code: "ST-0003", carrier_type: CARRIER_TYPE },
    batch_carrier_assignment_id: "bca-3", seeds_sown: 200, state: "in_germination",
    placement: {
      trolley: { id: "t8", code: "GT-08", name: "Trolley 8" },
      chamber: { id: "c8", code: "GC-08", name: "Chamber 8" },
      position: { id: "l8", code: "GT-08-L01", name: "Level", level_code: "GT-08-L01", mode: "direct" },
    },
  },
  {
    batch_id: "batch-4", batch_code: "CB-0004", seed_lot: SEED_LOT,
    tray: { id: "tray-4", code: "ST-0004", carrier_type: CARRIER_TYPE },
    batch_carrier_assignment_id: "bca-4", seeds_sown: 150, state: "elsewhere", placement: null,
  },
];

function outcomeSnapshot(overrides: Record<string, unknown> = {}) {
  return {
    id: "snap-1", observation_event_id: "ev-1", tray: TRAYS[2].tray, batch_carrier_assignment_id: "bca-3",
    normal_seedling_count: 180, abnormal_seedling_count: 10, living_seedling_count: 190, assessment_complete: true,
    note: null, effective_time: "2026-08-10T09:00:00Z", recorded_time: "2026-08-10T09:00:00Z", actor_user_id: "user-1",
    ...overrides,
  };
}

function emptyOutcomes(batchId: string, batchCode: string) {
  return {
    batch_id: batchId, batch_code: batchCode, trays: [],
    authoritative_living_seedling_total: 0, completed_tray_count: 0, unresolved_tray_count: 0, all_resolved: false,
  };
}

const OUTCOMES_BY_BATCH: Record<string, unknown> = {
  "batch-1": emptyOutcomes("batch-1", "CB-0001"),
  "batch-2": {
    batch_id: "batch-2", batch_code: "CB-0002",
    trays: [
      {
        batch_carrier_assignment_id: "bca-2", tray: TRAYS[1].tray, batch_id: "batch-2", batch_code: "CB-0002",
        seeds_sown: 180, sown_site_count: null, current_placement: "in_germination", latest_snapshot: null,
        latest_completed_snapshot: null, current_normal_seedling_count: null, current_abnormal_seedling_count: null,
        current_living_seedling_count: null, current_seed_to_living_gap_count: null, living_seedling_yield_percent: null,
        assessment_complete: false, authoritative_living_seedling_count: null, latest_effective_time: null,
        historical_snapshot_count: 0,
      },
    ],
    authoritative_living_seedling_total: 0, completed_tray_count: 0, unresolved_tray_count: 1, all_resolved: false,
  },
  "batch-3": {
    batch_id: "batch-3", batch_code: "CB-0003",
    trays: [
      {
        batch_carrier_assignment_id: "bca-3", tray: TRAYS[2].tray, batch_id: "batch-3", batch_code: "CB-0003",
        seeds_sown: 200, sown_site_count: null, current_placement: "in_germination",
        latest_snapshot: outcomeSnapshot(), latest_completed_snapshot: outcomeSnapshot(),
        current_normal_seedling_count: 180, current_abnormal_seedling_count: 10, current_living_seedling_count: 190,
        current_seed_to_living_gap_count: 10, living_seedling_yield_percent: "95.00", assessment_complete: true,
        authoritative_living_seedling_count: 190, latest_effective_time: "2026-08-10T09:00:00Z",
        historical_snapshot_count: 1,
      },
    ],
    authoritative_living_seedling_total: 190, completed_tray_count: 1, unresolved_tray_count: 0, all_resolved: true,
  },
  "batch-4": emptyOutcomes("batch-4", "CB-0004"),
};

const SEEDLING_TRAYS = [
  {
    batch_id: "batch-2", batch_code: "CB-0002", seed_lot: SEED_LOT, tray: TRAYS[1].tray,
    batch_carrier_assignment_id: "bca-2", seeds_sown: 180, germination_handoff: null, seedling_entry: null,
    current_placement: { kind: "in_germination", germination: null, seedling_table: null }, state: "no_completed_handoff",
  },
  {
    batch_id: "batch-3", batch_code: "CB-0003", seed_lot: SEED_LOT, tray: TRAYS[2].tray,
    batch_carrier_assignment_id: "bca-3", seeds_sown: 200,
    germination_handoff: { normal_seedling_count: 180, abnormal_seedling_count: 10, living_seedling_count: 190, effective_time: "2026-08-10T09:00:00Z" },
    seedling_entry: null, current_placement: { kind: "in_germination", germination: null, seedling_table: null },
    state: "ready_for_seedling",
  },
  {
    batch_id: "batch-4", batch_code: "CB-0004", seed_lot: SEED_LOT, tray: TRAYS[3].tray,
    batch_carrier_assignment_id: "bca-4", seeds_sown: 150,
    germination_handoff: { normal_seedling_count: 140, abnormal_seedling_count: 5, living_seedling_count: 145, effective_time: "2026-08-01T00:00:00Z" },
    seedling_entry: { id: "se-1", movement_id: "mv-1", source_germination_outcome_snapshot_id: "gos-1", starting_living_seedling_count: 145, effective_time: "2026-08-02T00:00:00Z" },
    current_placement: { kind: "on_seedling_table", germination: null, seedling_table: { id: "table-9", code: "ST09", name: "Table 9" } },
    state: "in_seedling",
  },
];

const TROLLEYS = [
  { id: "trolley-1", code: "GT-01", name: "Trolley 1", chamber: { id: "chamber-1", code: "GC-01", name: "Chamber 1" }, total_capacity: 6, occupied_count: 1, available_capacity: 5 },
];
const LEVELS = [
  { id: "level-1", code: "GT-01-L01", name: "Level GT-01-L01", mode: "direct", capacity: 4, occupied_count: 1, available_capacity: 3, slots: [] },
];

function stubFetch(overrides: Record<string, unknown> = {}) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (init?.method === "POST" && url.includes("/germination/tray-placements")) {
        return jsonResponse(
          overrides.placementResponse ?? {
            movement_id: "mv-place-1", client_command_id: "cmd-1", tray: { id: "tray-1", code: "ST-0001", carrier_type: CARRIER_TYPE },
            batch_code: "CB-0001", seeds_sown: 200,
            trolley: { id: "trolley-1", code: "GT-01", name: "Trolley 1" },
            chamber: { id: "chamber-1", code: "GC-01", name: "Chamber 1" },
            position: { id: "level-1", code: "GT-01-L01", name: "Level GT-01-L01", level_code: "GT-01-L01", mode: "direct" },
            effective_time: "2026-08-20T09:00:00Z",
          },
          201,
        );
      }
      if (init?.method === "POST" && url.includes("/germination-outcomes")) {
        return jsonResponse(overrides.outcomePostResponse ?? { detail: "not stubbed for this test" }, overrides.outcomePostResponse ? 201 : 500);
      }
      if (init?.method === "POST" && url.includes("/nursery/seedling/entries")) {
        return jsonResponse(overrides.seedlingPostResponse ?? { detail: "not stubbed for this test" }, overrides.seedlingPostResponse ? 201 : 500);
      }
      if (url.includes("/germination/trays")) {
        if (overrides.traysError) return jsonResponse({ detail: "Server error" }, 500);
        return jsonResponse(overrides.trays ?? TRAYS);
      }
      if (url.includes("/germination/chambers/available")) return jsonResponse(overrides.chambers ?? []);
      if (url.includes("/germination/trolleys/available")) return jsonResponse(overrides.trolleys ?? TROLLEYS);
      if (url.includes("/levels")) return jsonResponse(overrides.levels ?? LEVELS);
      if (url.includes("/germination-outcomes/current")) {
        const batchId = url.match(/crop-batches\/([^/]+)\//)?.[1] ?? "";
        const map = (overrides.outcomesByBatch as Record<string, unknown>) ?? OUTCOMES_BY_BATCH;
        return jsonResponse(map[batchId] ?? emptyOutcomes(batchId, ""));
      }
      if (url.includes("/nursery/seedling/trays")) return jsonResponse(overrides.seedlingTrays ?? SEEDLING_TRAYS);
      if (url.includes("/nursery/seedling/tables/available")) return jsonResponse(overrides.seedlingTables ?? []);
      if (url.includes("/assets")) return jsonResponse(overrides.assets ?? []);
      return jsonResponse([]);
    }),
  );
}

beforeEach(() => {
  Array.from(searchParams.keys()).forEach((key) => searchParams.delete(key));
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("GerminationPage worklist", () => {
  it("shows an empty state when there are no Sown Seed Trays yet", async () => {
    stubFetch({ trays: [] });
    render(withQueryClient(<GerminationPage />));
    await waitFor(() => expect(screen.getByText("No Sown Seed Trays yet")).toBeInTheDocument());
  });

  it("renders the worklist with truthful, human-readable next actions per row -- no raw UUIDs, no fabricated action for an ineligible Tray", async () => {
    stubFetch();
    render(withQueryClient(<GerminationPage />));
    await waitFor(() => expect(screen.getByText("ST-0001")).toBeInTheDocument());

    expect(screen.getByRole("button", { name: "Move to Germination" })).toBeInTheDocument(); // Row A (bca-1)
    expect(screen.getByRole("button", { name: "Record outcome" })).toBeInTheDocument(); // Row B (bca-2)
    // Only Row C (bca-3) is truthfully ready -- never fabricated for Row B/D.
    expect(screen.getAllByRole("button", { name: "Move to Seedling" })).toHaveLength(1);
    // Row D (bca-4, already in Seedling): no truthful next action here.
    expect(screen.getByText("ST-0004")).toBeInTheDocument();

    expect(
      screen.queryByText(/batch-1|batch-2|batch-3|batch-4|bca-1|bca-2|bca-3|bca-4|tray-1|tray-2|tray-3|tray-4/),
    ).not.toBeInTheDocument();
  });

  it("clicking a row's Move to Germination freezes that exact Tray, and the placement receipt offers only the truthful next action", async () => {
    // Stateful: once placement succeeds, the worklist's own refetch must see
    // bca-1 as placed (authoritative), never assumed client-side.
    let placed = false;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (init?.method === "POST" && url.includes("/germination/tray-placements")) {
          placed = true;
          return jsonResponse(
            {
              movement_id: "mv-place-1", client_command_id: "cmd-1", tray: TRAYS[0].tray, batch_code: "CB-0001", seeds_sown: 200,
              trolley: { id: "trolley-1", code: "GT-01", name: "Trolley 1" }, chamber: { id: "chamber-1", code: "GC-01", name: "Chamber 1" },
              position: { id: "level-1", code: "GT-01-L01", name: "Level GT-01-L01", level_code: "GT-01-L01", mode: "direct" },
              effective_time: "2026-08-20T09:00:00Z",
            },
            201,
          );
        }
        if (url.includes("/germination/trays")) {
          return jsonResponse(
            placed
              ? [
                  {
                    ...TRAYS[0], state: "in_germination",
                    placement: {
                      trolley: { id: "trolley-1", code: "GT-01", name: "Trolley 1" },
                      chamber: { id: "chamber-1", code: "GC-01", name: "Chamber 1" },
                      position: { id: "level-1", code: "GT-01-L01", name: "Level GT-01-L01", level_code: "GT-01-L01", mode: "direct" },
                    },
                  },
                  ...TRAYS.slice(1),
                ]
              : TRAYS,
          );
        }
        if (url.includes("/germination/trolleys/available")) return jsonResponse(TROLLEYS);
        if (url.includes("/levels")) return jsonResponse(LEVELS);
        if (url.includes("/germination-outcomes/current")) {
          const batchId = url.match(/crop-batches\/([^/]+)\//)?.[1] ?? "";
          return jsonResponse(OUTCOMES_BY_BATCH[batchId] ?? emptyOutcomes(batchId, ""));
        }
        if (url.includes("/nursery/seedling/trays")) return jsonResponse(SEEDLING_TRAYS);
        return jsonResponse([]);
      }),
    );
    render(withQueryClient(<GerminationPage />));
    await waitFor(() => expect(screen.getByText("ST-0001")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "Move to Germination" }));
    await waitFor(() => expect(screen.getByText(/from the germination worklist/i)).toBeInTheDocument());
    expect(screen.queryByLabelText(/^seed tray$/i)).not.toBeInTheDocument();

    await waitFor(() => expect(screen.getByText(/GT-01 — GC-01/)).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText(/^trolley$/i), { target: { value: "trolley-1" } });
    await waitFor(() => expect(screen.getByText(/GT-01-L01/)).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText(/^level$/i), { target: { value: "level-1" } });
    fireEvent.click(screen.getByRole("button", { name: "Review" }));
    await waitFor(() => expect(screen.getByText("Review before moving")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Move to Germination" }));

    await waitFor(() =>
      expect(screen.getByText(/Seed Tray ST-0001 \(CB-0001\) moved to Trolley GT-01 \/ Chamber GC-01 \/ GT-01-L01/)).toBeInTheDocument(),
    );
    // Bca-1 is now placed and unobserved -- the truthful next step is offered directly.
    expect(screen.getByRole("button", { name: "Record outcome" })).toBeInTheDocument();
  });

  it("clicking a row's Record outcome opens with that exact assignment frozen -- no reselection", async () => {
    stubFetch();
    render(withQueryClient(<GerminationPage />));
    await waitFor(() => expect(screen.getByText("ST-0001")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "Record outcome" }));
    await waitFor(() => expect(screen.getByText(/from the germination worklist/i)).toBeInTheDocument());
    expect(screen.getByText("CB-0002 — ST-0002")).toBeInTheDocument();
    expect(screen.queryByLabelText(/^seed tray$/i)).not.toBeInTheDocument();
  });

  it("a final outcome success offers Move to Seedling only once the worklist authoritatively confirms eligibility, and Seedling Entry retains the exact assignment", async () => {
    let completed = false;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (init?.method === "POST" && url.includes("/germination-outcomes")) {
          completed = true;
          return jsonResponse(
            {
              observation_event_id: "ev-9", client_command_id: "cmd-9", batch_id: "batch-2",
              effective_time: "2026-08-20T09:00:00Z", note: null,
              snapshots: [outcomeSnapshot({ id: "snap-9", batch_carrier_assignment_id: "bca-2", tray: TRAYS[1].tray, normal_seedling_count: 190, abnormal_seedling_count: 6, living_seedling_count: 196 })],
            },
            201,
          );
        }
        if (init?.method === "POST" && url.includes("/nursery/seedling/entries")) {
          return jsonResponse(
            {
              id: "se-x", client_command_id: "cmd-10", batch_id: "batch-2", batch_code: "CB-0002",
              batch_carrier_assignment_id: "bca-2", tray: TRAYS[1].tray,
              seedling_table: { id: "table-1", code: "ST01", name: "Table 1" }, movement_id: "mv-x",
              source_germination_outcome_snapshot_id: "snap-9", source_normal_seedling_count: 190,
              source_abnormal_seedling_count: 6, source_effective_time: "2026-08-20T09:00:00Z",
              starting_living_seedling_count: 196, effective_time: "2026-08-20T10:00:00Z", recorded_at: "2026-08-20T10:00:00Z",
            },
            201,
          );
        }
        if (url.includes("/germination/trays")) return jsonResponse(TRAYS);
        if (url.includes("/germination-outcomes/current")) {
          const batchId = url.match(/crop-batches\/([^/]+)\//)?.[1] ?? "";
          if (batchId === "batch-2" && completed) {
            return jsonResponse({
              batch_id: "batch-2", batch_code: "CB-0002",
              trays: [{
                ...(OUTCOMES_BY_BATCH["batch-2"] as { trays: unknown[] }).trays[0] as object,
                latest_snapshot: outcomeSnapshot({ id: "snap-9", batch_carrier_assignment_id: "bca-2", tray: TRAYS[1].tray, normal_seedling_count: 190, abnormal_seedling_count: 6, living_seedling_count: 196 }),
                assessment_complete: true, current_normal_seedling_count: 190, current_abnormal_seedling_count: 6,
                current_living_seedling_count: 196, historical_snapshot_count: 1,
              }],
              authoritative_living_seedling_total: 196, completed_tray_count: 1, unresolved_tray_count: 0, all_resolved: true,
            });
          }
          return jsonResponse(OUTCOMES_BY_BATCH[batchId] ?? emptyOutcomes(batchId, ""));
        }
        if (url.includes("/nursery/seedling/trays")) {
          if (completed) {
            return jsonResponse([
              { ...SEEDLING_TRAYS[0], state: "ready_for_seedling", germination_handoff: { normal_seedling_count: 190, abnormal_seedling_count: 6, living_seedling_count: 196, effective_time: "2026-08-20T09:00:00Z" } },
              SEEDLING_TRAYS[1],
              SEEDLING_TRAYS[2],
            ]);
          }
          return jsonResponse(SEEDLING_TRAYS);
        }
        if (url.includes("/nursery/seedling/tables/available")) return jsonResponse([{ id: "table-1", code: "ST01", name: "Table 1", capacity: 4, active_tray_count: 0, remaining_capacity: 4, seedling_area: { id: "area-1", code: "SA", name: "Seedling Area" }, greenhouse: { id: "gh-1", code: "NUR", name: "Nursery" } }]);
        return jsonResponse([]);
      }),
    );

    render(withQueryClient(<GerminationPage />));
    await waitFor(() => expect(screen.getByText("ST-0002")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Record outcome" }));
    await waitFor(() => expect(screen.getByText("CB-0002 — ST-0002")).toBeInTheDocument());

    fireEvent.change(screen.getByLabelText(/^normal seedlings$/i), { target: { value: "190" } });
    fireEvent.change(screen.getByLabelText(/^abnormal seedlings$/i), { target: { value: "6" } });
    fireEvent.click(screen.getByLabelText(/assessment complete/i));
    fireEvent.click(screen.getByRole("button", { name: "Review" }));
    await waitFor(() => expect(screen.getByText("Review before completing")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Complete Outcome" }));

    await waitFor(() =>
      expect(screen.getByText(/Outcome recorded for CB-0002 — ST-0002: 190 normal \/ 6 abnormal seedlings \(final\)/)).toBeInTheDocument(),
    );
    // Truthful, not optimistic: appears only once the worklist itself (re-fetched) confirms eligibility.
    const moveToSeedling = await screen.findByRole("button", { name: "Move to Seedling" }, { timeout: 3000 });
    fireEvent.click(moveToSeedling);

    // Same assignment retained -- no reselection.
    await waitFor(() => expect(screen.getByText("CB-0002 — ST-0002")).toBeInTheDocument());
    expect(screen.queryByLabelText(/^seed tray$/i)).not.toBeInTheDocument();

    await waitFor(() => expect(screen.getByText(/ST01 — Seedling Area/)).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText(/seedling table/i), { target: { value: "table-1" } });
    fireEvent.click(screen.getByRole("button", { name: "Review" }));
    await waitFor(() => expect(screen.getByText("Review before moving to Seedling")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Move to Seedling" }));

    await waitFor(() =>
      expect(screen.getByText(/Seed Tray ST-0002 \(CB-0002\) moved to Seedling Table ST01 — 196 living seedlings/)).toBeInTheDocument(),
    );
  });

  it("seeds the Batch filter from the incoming URL context and keeps it editable", async () => {
    searchParams.set("batchId", "batch-2");
    stubFetch();
    render(withQueryClient(<GerminationPage />));
    await waitFor(() => expect(screen.getByText("ST-0002")).toBeInTheDocument());
    expect(screen.queryByText("ST-0001")).not.toBeInTheDocument();
    expect(screen.queryByText("ST-0003")).not.toBeInTheDocument();
    expect((screen.getByLabelText(/^batch$/i) as HTMLSelectElement).value).toBe("batch-2");

    fireEvent.change(screen.getByLabelText(/^batch$/i), { target: { value: "" } });
    await waitFor(() => expect(screen.getByText("ST-0001")).toBeInTheDocument());
  });

  it("Move All (header bulk placement) still reports truthful partial success from the page", async () => {
    const BATCH1_TRAYS = [
      TRAYS[0],
      { ...TRAYS[0], tray: { id: "tray-1b", code: "ST-0001B", carrier_type: CARRIER_TYPE }, batch_carrier_assignment_id: "bca-1b" },
    ];
    let placementCalls = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (init?.method === "POST" && url.includes("/germination/tray-placements")) {
          placementCalls += 1;
          if (placementCalls === 2) return jsonResponse({ detail: "Level is full" }, 422);
          return jsonResponse(
            { movement_id: "mv-1", client_command_id: "c1", tray: BATCH1_TRAYS[0].tray, batch_code: "CB-0001", seeds_sown: 200, trolley: TROLLEYS[0], chamber: TROLLEYS[0].chamber, position: LEVELS[0], effective_time: "2026-08-20T09:00:00Z" },
            201,
          );
        }
        if (url.includes("/germination/trays")) return jsonResponse(BATCH1_TRAYS);
        if (url.includes("/germination/trolleys/available")) return jsonResponse(TROLLEYS);
        if (url.includes("/levels")) return jsonResponse(LEVELS);
        if (url.includes("/germination-outcomes/current")) return jsonResponse(emptyOutcomes("batch-1", "CB-0001"));
        if (url.includes("/nursery/seedling/trays")) return jsonResponse([]);
        return jsonResponse([]);
      }),
    );
    searchParams.set("batchId", "batch-1");

    render(withQueryClient(<GerminationPage />));
    await waitFor(() => expect(screen.getByText("ST-0001")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Move Tray to Germination" }));
    await waitFor(() => expect(screen.getByText(/2 trays ready/i)).toBeInTheDocument());
    await waitFor(() => expect(screen.getByText(/GT-01 — GC-01/)).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText(/^trolley$/i), { target: { value: "trolley-1" } });
    await waitFor(() => expect(screen.getByText(/GT-01-L01/)).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText(/^level$/i), { target: { value: "level-1" } });
    fireEvent.click(screen.getByRole("button", { name: "Move All 2 Trays" }));

    await waitFor(() => expect(screen.getByText("1 tray moved successfully")).toBeInTheDocument());
    expect(screen.getByText("1 tray remains")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Continue Remaining" })).toBeInTheDocument();
  });

  it("never represents abnormal/weak seedlings as loss anywhere in the worklist", async () => {
    stubFetch();
    render(withQueryClient(<GerminationPage />));
    await waitFor(() => expect(screen.getByText("ST-0003")).toBeInTheDocument());
    expect(screen.getByText(/180 normal \/ 10 abnormal/)).toBeInTheDocument();
    expect(screen.queryByText(/loss|weak seedling|non-germination/i)).not.toBeInTheDocument();
  });

  it("renders a query error as an error state, never a successful-empty worklist", async () => {
    stubFetch({ traysError: true });
    render(withQueryClient(<GerminationPage />));
    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
    expect(screen.queryByText("No Sown Seed Trays yet")).not.toBeInTheDocument();
  });

  it("opens the Place Trolley form and returns to the list on cancel", async () => {
    stubFetch();
    render(withQueryClient(<GerminationPage />));
    await waitFor(() => expect(screen.getByText("ST-0001")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Place Trolley" }));
    await waitFor(() => expect(screen.getByLabelText(/^trolley$/i)).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.getByText("ST-0001")).toBeInTheDocument());
  });
});
