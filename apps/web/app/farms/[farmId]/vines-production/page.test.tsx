import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { withQueryClient } from "@/lib/test-utils";

import VinesProductionPage from "./page";

vi.mock("next/navigation", () => ({
  useParams: () => ({ farmId: "farm-1" }),
}));

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

// Real UUID-shaped ids (never crop/variety/batch codes) -- backs the "no
// raw UUIDs rendered" requirement below with a realistic fixture rather
// than a fixture that happens to use short, human-looking ids.
const BATCH_ID = "11111111-1111-4111-8111-111111111111";
const GUTTER_ID = "22222222-2222-4222-8222-222222222222";
const GREENHOUSE_ID = "33333333-3333-4333-8333-333333333333";
const CROP_ID = "44444444-4444-4444-8444-444444444444";
const VARIETY_ID = "55555555-5555-4555-8555-555555555555";
const BCA_ONE_LIVING = "66666666-6666-4666-8666-666666666666";
const BCA_MULTI_LIVING = "77777777-7777-4777-8777-777777777777";
const GROW_CUBE_LIVING = "88888888-8888-4888-8888-888888888888";
const GROW_CUBE_REMOVED = "99999999-9999-4999-8999-999999999999";
const GROW_CUBE_A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const GROW_CUBE_B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";
const UUID_PATTERN = /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/i;

const GROW_BAG_CARRIER_TYPE = { id: "ct-bag", code: "grow_bag", name: "Grow Bag" };
const GROW_CUBE_CARRIER_TYPE = { id: "ct-cube", code: "grow_cube", name: "Grow Cube" };

const PLACEMENTS = [
  {
    batch_id: BATCH_ID, batch_code: "VIN-0142", crop_id: CROP_ID, crop_code: "TOM", crop_common_name: "Tomato",
    variety_id: VARIETY_ID, variety_code: "MAR", variety_name: "Marmande",
    greenhouse_id: GREENHOUSE_ID, greenhouse_code: "GH-04", greenhouse_name: "Vines Greenhouse",
    gutter_id: GUTTER_ID, gutter_code: "GUT-001",
    plant_count: 20, living_plant_count: 17, lost_plant_count: 3,
    earliest_assigned_effective_time: "2026-09-01T00:00:00Z", days_in_production: 8,
  },
];

// Grow Bag with capacity 2, one already-removed plant -- the sole living
// Grow Cube (GC-LIVE) is the "auto-select" scenario.
const GROW_BAGS_ONE_LIVING = [
  {
    grow_bag: { id: "bag-1", code: "GB-0001", carrier_type: GROW_BAG_CARRIER_TYPE },
    grow_bag_position_code: "POS-001", batch_carrier_assignment_id: BCA_ONE_LIVING,
    assigned_plant_count: 2, living_plant_count: 1, capacity: 2, free_capacity: 1,
    assigned_effective_time: "2026-09-01T00:00:00Z",
    grow_cubes: [
      { grow_cube: { id: GROW_CUBE_LIVING, code: "GC-LIVE", carrier_type: GROW_CUBE_CARRIER_TYPE }, source_seed_tray: null, status: "living", disposition: null },
      {
        grow_cube: { id: GROW_CUBE_REMOVED, code: "GC-GONE", carrier_type: GROW_CUBE_CARRIER_TYPE }, source_seed_tray: null,
        status: "removed", disposition: { reason_code: "dead", effective_time: "2026-09-05T00:00:00Z", note: null },
      },
    ],
  },
];

// Grow Bag with capacity 2, BOTH plants living -- the "manual multi-select"
// scenario (no auto-select should fire).
const GROW_BAGS_MULTI_LIVING = [
  {
    grow_bag: { id: "bag-2", code: "GB-0002", carrier_type: GROW_BAG_CARRIER_TYPE },
    grow_bag_position_code: "POS-002", batch_carrier_assignment_id: BCA_MULTI_LIVING,
    assigned_plant_count: 2, living_plant_count: 2, capacity: 2, free_capacity: 2,
    assigned_effective_time: "2026-09-01T00:00:00Z",
    grow_cubes: [
      { grow_cube: { id: GROW_CUBE_A, code: "GC-A", carrier_type: GROW_CUBE_CARRIER_TYPE }, source_seed_tray: null, status: "living", disposition: null },
      { grow_cube: { id: GROW_CUBE_B, code: "GC-B", carrier_type: GROW_CUBE_CARRIER_TYPE }, source_seed_tray: null, status: "living", disposition: null },
    ],
  },
];

const RECORD_RESULT = {
  command_id: "cmd-1", client_command_id: "x", batch_carrier_assignment_id: BCA_ONE_LIVING,
  population_root_batch_carrier_assignment_id: BCA_ONE_LIVING,
  event: {
    id: "evt-1", command_id: "cmd-1", batch_carrier_assignment_id: BCA_ONE_LIVING,
    population_root_batch_carrier_assignment_id: BCA_ONE_LIVING, event_kind: "REDUCTION", reason_code: "dead",
    quantity_delta: -1, plant_loss_quantity: 1, effective_time: "2026-09-08T09:00:00Z",
    recorded_at: "2026-09-08T09:00:00Z", note: null, reverses_event_id: null, is_reversed: false,
    actor_user_id: "user-1", grow_cubes: [{ id: GROW_CUBE_LIVING, code: "GC-LIVE", carrier_type: GROW_CUBE_CARRIER_TYPE }],
  },
  previous_living_population: 1, resulting_living_population: 0, assignment_released: true,
};

const HISTORY = [
  {
    population_root_batch_carrier_assignment_id: BCA_ONE_LIVING, grow_bag_code: "GB-0001", batch_id: BATCH_ID,
    batch_code: "VIN-0142", gutter_code: "GUT-001", opening_population: 2, current_living_population: 1,
    is_active: true,
    events: [
      {
        id: "evt-1", command_id: "cmd-1", batch_carrier_assignment_id: BCA_ONE_LIVING,
        population_root_batch_carrier_assignment_id: BCA_ONE_LIVING, event_kind: "REDUCTION", reason_code: "dead",
        quantity_delta: -1, plant_loss_quantity: 1, effective_time: "2026-09-05T00:00:00Z",
        recorded_at: "2026-09-05T00:00:00Z", note: null, reverses_event_id: null, is_reversed: false,
        actor_user_id: "user-1", grow_cubes: [{ id: GROW_CUBE_REMOVED, code: "GC-GONE", carrier_type: GROW_CUBE_CARRIER_TYPE }],
      },
    ],
  },
];

// A voided (corrected) loss: the original REDUCTION is marked reversed, and
// its own REVERSAL restores the population -- both rows remain visible.
const VOID_HISTORY = [
  {
    population_root_batch_carrier_assignment_id: BCA_ONE_LIVING, grow_bag_code: "GB-0001", batch_id: BATCH_ID,
    batch_code: "VIN-0142", gutter_code: "GUT-001", opening_population: 2, current_living_population: 2,
    is_active: true,
    events: [
      {
        id: "evt-1", command_id: "cmd-1", batch_carrier_assignment_id: BCA_ONE_LIVING,
        population_root_batch_carrier_assignment_id: BCA_ONE_LIVING, event_kind: "REDUCTION", reason_code: "dead",
        quantity_delta: -1, plant_loss_quantity: 1, effective_time: "2026-09-05T00:00:00Z",
        recorded_at: "2026-09-05T00:00:00Z", note: null, reverses_event_id: null, is_reversed: true,
        actor_user_id: "user-1", grow_cubes: [{ id: GROW_CUBE_REMOVED, code: "GC-GONE", carrier_type: GROW_CUBE_CARRIER_TYPE }],
      },
      {
        id: "evt-2", command_id: "cmd-2", batch_carrier_assignment_id: BCA_ONE_LIVING,
        population_root_batch_carrier_assignment_id: BCA_ONE_LIVING, event_kind: "REVERSAL", reason_code: "dead",
        quantity_delta: 1, plant_loss_quantity: 0, effective_time: "2026-09-05T00:00:00Z",
        recorded_at: "2026-09-05T01:00:00Z", note: null, reverses_event_id: "evt-1", is_reversed: false,
        actor_user_id: "user-1", grow_cubes: [],
      },
    ],
  },
];

function stubFetch(overrides: Record<string, unknown> = {}) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.includes("/grow-bags")) return jsonResponse(overrides.growBags ?? GROW_BAGS_ONE_LIVING);
      if (url.includes("/vines-production/placements")) return jsonResponse(overrides.placements ?? PLACEMENTS);
      if (url.includes("/dispositions") && url.includes("/correct")) {
        return jsonResponse(overrides.correctResult ?? {});
      }
      if (url.includes("/dispositions") && (!init || init.method === undefined || init.method === "GET")) {
        return jsonResponse(overrides.history ?? []);
      }
      if (url.includes("/dispositions")) return jsonResponse(overrides.recordResult ?? RECORD_RESULT);
      return jsonResponse([]);
    }),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

async function expandPopulationRow() {
  await waitFor(() => expect(screen.getByText("VIN-0142")).toBeInTheDocument());
  fireEvent.click(screen.getByRole("button", { name: /grow bags/i }));
}

describe("VinesProductionPage", () => {
  // --- 1. Population view --------------------------------------------------

  it("renders aggregated Batch/Gutter population with Living/Lost, and shows no raw UUIDs", async () => {
    stubFetch();
    render(withQueryClient(<VinesProductionPage />));
    await waitFor(() => expect(screen.getByText("VIN-0142")).toBeInTheDocument());

    expect(screen.getByText("Tomato")).toBeInTheDocument();
    expect(screen.getByText("Marmande")).toBeInTheDocument();
    expect(screen.getByText("GH-04")).toBeInTheDocument();
    expect(screen.getByText("GUT-001")).toBeInTheDocument();
    expect(screen.getByText("17")).toBeInTheDocument(); // Living Plants
    expect(screen.getByText("3")).toBeInTheDocument(); // Lost
    expect(screen.getByText("8")).toBeInTheDocument(); // Days in Production

    expect(document.body.textContent).not.toMatch(UUID_PATTERN);
  });

  it("drill-down shows Grow Bag Living/Capacity/Free values, no raw UUIDs", async () => {
    stubFetch();
    render(withQueryClient(<VinesProductionPage />));
    await expandPopulationRow();

    await waitFor(() => expect(screen.getByText(/GB-0001/)).toBeInTheDocument());
    expect(screen.getByText(/Living 1 \/ 2/)).toBeInTheDocument();
    expect(screen.getByText(/Free 1/)).toBeInTheDocument();
    expect(screen.getByText("GC-LIVE")).toBeInTheDocument();
    expect(screen.getByText(/GC-GONE/)).toBeInTheDocument();

    expect(document.body.textContent).not.toMatch(UUID_PATTERN);
  });

  // --- 2. Record Plant Loss --------------------------------------------------

  it("auto-selects the sole living Grow Cube in a 1-plant Grow Bag", async () => {
    stubFetch();
    render(withQueryClient(<VinesProductionPage />));
    await expandPopulationRow();
    await waitFor(() => expect(screen.getByText(/GB-0001/)).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /record plant loss/i }));

    await waitFor(() => expect(screen.getByText("Record Plant Loss — GB-0001")).toBeInTheDocument());
    expect(screen.getByRole("checkbox", { name: "GC-LIVE" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: /GC-GONE/ })).not.toBeChecked();
    expect(screen.getByRole("checkbox", { name: /GC-GONE/ })).toBeDisabled();

    fireEvent.change(screen.getByLabelText(/^reason$/i), { target: { value: "dead" } });
    fireEvent.click(screen.getByRole("button", { name: "Review" }));

    await waitFor(() => expect(screen.getByText("Review before recording")).toBeInTheDocument());
    expect(screen.getByText("GC-LIVE")).toBeInTheDocument();
  });

  it("allows selecting specific Grow Cube(s) in a multi-plant Grow Bag (no auto-select)", async () => {
    stubFetch({ growBags: GROW_BAGS_MULTI_LIVING });
    render(withQueryClient(<VinesProductionPage />));
    await expandPopulationRow();
    await waitFor(() => expect(screen.getByText(/GB-0002/)).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /record plant loss/i }));

    await waitFor(() => expect(screen.getByText("Record Plant Loss — GB-0002")).toBeInTheDocument());
    expect(screen.getByRole("checkbox", { name: "GC-A" })).not.toBeChecked();
    expect(screen.getByRole("checkbox", { name: "GC-B" })).not.toBeChecked();

    fireEvent.click(screen.getByRole("checkbox", { name: "GC-A" }));
    fireEvent.change(screen.getByLabelText(/^reason$/i), { target: { value: "dead" } });
    fireEvent.click(screen.getByRole("button", { name: "Review" }));

    await waitFor(() => expect(screen.getByText("Review before recording")).toBeInTheDocument());
    expect(screen.getByText("GC-A")).toBeInTheDocument();
    const dialog = screen.getByText("Affected plant(s)").closest("div") as HTMLElement;
    expect(dialog.textContent).not.toContain("GC-B");
  });

  it("requires a reason before proceeding to review", async () => {
    stubFetch();
    render(withQueryClient(<VinesProductionPage />));
    await expandPopulationRow();
    await waitFor(() => expect(screen.getByText(/GB-0001/)).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /record plant loss/i }));
    await waitFor(() => expect(screen.getByText("Record Plant Loss — GB-0001")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "Review" }));

    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(/reason is required/i));
    expect(screen.queryByText("Review before recording")).not.toBeInTheDocument();
  });

  it("submits the exact RecordVinesGrowCubeDispositionCreate payload on confirm", async () => {
    let recordBody: Record<string, unknown> | null = null;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.includes("/grow-bags")) return jsonResponse(GROW_BAGS_ONE_LIVING);
        if (url.includes("/vines-production/placements")) return jsonResponse(PLACEMENTS);
        if (url.includes("/dispositions") && init?.method === "POST") {
          recordBody = JSON.parse(String(init.body));
          return jsonResponse(RECORD_RESULT);
        }
        if (url.includes("/dispositions")) return jsonResponse([]);
        return jsonResponse([]);
      }),
    );
    render(withQueryClient(<VinesProductionPage />));
    await expandPopulationRow();
    await waitFor(() => expect(screen.getByText(/GB-0001/)).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /record plant loss/i }));
    await waitFor(() => expect(screen.getByText("Record Plant Loss — GB-0001")).toBeInTheDocument());

    fireEvent.change(screen.getByLabelText(/^reason$/i), { target: { value: "dead" } });
    fireEvent.change(screen.getByLabelText(/^date$/i), { target: { value: "2026-09-08" } });
    fireEvent.change(screen.getByLabelText(/^time$/i), { target: { value: "09:00" } });
    fireEvent.click(screen.getByRole("button", { name: "Review" }));
    await waitFor(() => expect(screen.getByText("Review before recording")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));

    await waitFor(() => expect(screen.getByText(/plant loss recorded/i)).toBeInTheDocument());
    expect(recordBody).toMatchObject({
      batch_carrier_assignment_id: BCA_ONE_LIVING, grow_cube_carrier_ids: [GROW_CUBE_LIVING], reason_code: "dead",
      note: null,
    });
    expect(typeof (recordBody as unknown as { client_command_id: string }).client_command_id).toBe("string");
  });

  // --- 3. Loss History --------------------------------------------------

  it("Loss History tab renders recorded loss with operator-friendly reason/status wording", async () => {
    stubFetch({ history: HISTORY });
    render(withQueryClient(<VinesProductionPage />));
    await waitFor(() => expect(screen.getByText("VIN-0142")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("tab", { name: /loss history/i }));

    await waitFor(() => expect(screen.getByText(/GB-0001 — VIN-0142/)).toBeInTheDocument());
    expect(screen.getByText(/Loss 1 — Dead/)).toBeInTheDocument();
    expect(screen.getByText(/Plant\(s\): GC-GONE/)).toBeInTheDocument();
    expect(screen.getByText("Active")).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(UUID_PATTERN);
  });

  it("shows a corrected/voided record truthfully rather than as current active loss", async () => {
    stubFetch({ history: VOID_HISTORY });
    render(withQueryClient(<VinesProductionPage />));
    await waitFor(() => expect(screen.getByText("VIN-0142")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("tab", { name: /loss history/i }));

    await waitFor(() => expect(screen.getByText(/Loss 1 — Dead/)).toBeInTheDocument());
    // The original REDUCTION stays visible but is explicitly marked corrected...
    expect(screen.getByText(/Corrected — see reversal below/)).toBeInTheDocument();
    // ...and its own REVERSAL is shown as a restoration, never as "Reversal".
    expect(screen.getByText(/Restored 1 — Dead/)).toBeInTheDocument();
    expect(screen.queryByText(/^Reversal/)).not.toBeInTheDocument();
    // Current living population reflects the correction (back to opening),
    // never the stale as-if-still-lost figure.
    expect(screen.getByText(/Current 2/)).toBeInTheDocument();
  });
});
