import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { withQueryClient } from "@/lib/test-utils";

import LeafyProductionPage from "./page";

vi.mock("next/navigation", () => ({
  useParams: () => ({ farmId: "farm-1" }),
}));

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const ACTIVE_PLATES = [
  {
    carrier_id: "carrier-1", plate_code: "PP-001", batch_carrier_assignment_id: "bca-1",
    population_root_batch_carrier_assignment_id: "bca-1", batch_id: "batch-1", batch_code: "ICE-0142",
    crop_common_name: "Iceberg Lettuce", variety_name: "Mamutik", opening_population: 180,
    current_living_population: 180, total_recorded_loss: 0,
    current_location: { id: "loc-1", code: "TA01", name: "TA01", location_type_code: "grow_table", ancestry_label: "LEAFY-01 / Z01 / S01 / TA01" },
    has_location_warning: false,
  },
];

const ZERO_PLATE = {
  carrier_id: "carrier-2", plate_code: "PP-002", batch_carrier_assignment_id: "bca-2",
  population_root_batch_carrier_assignment_id: "bca-2", batch_id: "batch-1", batch_code: "ICE-0142",
  crop_common_name: "Iceberg Lettuce", variety_name: null, opening_population: 5,
  current_living_population: 5, total_recorded_loss: 0, current_location: null, has_location_warning: true,
};

const HISTORY = [
  {
    population_root_batch_carrier_assignment_id: "bca-1", plate_code: "PP-001", batch_id: "batch-1",
    batch_code: "ICE-0142", opening_population: 180, current_living_population: 175, is_active: true,
    events: [
      {
        id: "evt-1", command_id: "cmd-1", batch_carrier_assignment_id: "bca-1",
        population_root_batch_carrier_assignment_id: "bca-1", event_kind: "REDUCTION", reason_code: "dead",
        quantity_delta: -5, plant_loss_quantity: 5, effective_time: "2026-08-20T10:00:00Z",
        recorded_at: "2026-08-20T10:00:00Z", note: null, reverses_event_id: null, corrects_event_id: null,
        is_reversed: false, actor_user_id: "user-1",
      },
    ],
  },
];

function stubFetch(overrides: Record<string, unknown> = {}) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.includes("/leafy-production/active-plates")) return jsonResponse(overrides.activePlates ?? ACTIVE_PLATES);
      if (url.includes("/leafy-production/dispositions") && (!init || init.method === undefined || init.method === "GET")) {
        return jsonResponse(overrides.history ?? HISTORY);
      }
      if (url.includes("/correct")) {
        if (overrides.correctError) return jsonResponse({ detail: "conflict" }, 409);
        return jsonResponse(
          overrides.correctResult ?? {
            command_id: "cmd-2", client_command_id: "x", population_root_batch_carrier_assignment_id: "bca-1",
            target_event: HISTORY[0].events[0], reversal_event: { ...HISTORY[0].events[0], id: "evt-2", event_kind: "REVERSAL", quantity_delta: 5 },
            replacement_event: null, restored_batch_carrier_assignment_id: null,
            previous_living_population: 175, resulting_living_population: 180,
          },
        );
      }
      if (url.includes("/leafy-production/dispositions")) {
        if (overrides.recordError) return jsonResponse({ detail: "conflict" }, 409);
        return jsonResponse(
          overrides.recordResult ?? {
            command_id: "cmd-1", client_command_id: "x", batch_carrier_assignment_id: "bca-1",
            population_root_batch_carrier_assignment_id: "bca-1", event: HISTORY[0].events[0],
            previous_living_population: 180, resulting_living_population: 175, assignment_released: false,
          },
        );
      }
      return jsonResponse([]);
    }),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("LeafyProductionPage", () => {
  it("renders the Active Production Plates list", async () => {
    stubFetch();
    render(withQueryClient(<LeafyProductionPage />));
    await waitFor(() => expect(screen.getByText("PP-001 — ICE-0142")).toBeInTheDocument());
    expect(screen.getByText(/Living 180/)).toBeInTheDocument();
    expect(screen.getByText("LEAFY-01 / Z01 / S01 / TA01")).toBeInTheDocument();
  });

  it("breadcrumbs the grouped-nav parent (Production Operations), not the stale flat-nav Batches label", async () => {
    stubFetch();
    render(withQueryClient(<LeafyProductionPage />));
    await waitFor(() => expect(screen.getByText("PP-001 — ICE-0142")).toBeInTheDocument());
    expect(screen.getByText("Production Operations")).toBeInTheDocument();
    expect(screen.queryByText("Batches")).not.toBeInTheDocument();
  });

  it("shows a location warning for a Plate with no current Leafy location", async () => {
    stubFetch({ activePlates: [ZERO_PLATE] });
    render(withQueryClient(<LeafyProductionPage />));
    await waitFor(() => expect(screen.getByText("PP-002 — ICE-0142")).toBeInTheDocument());
    expect(screen.getByText(/No current Leafy location on record/)).toBeInTheDocument();
  });

  it("completes the full Record Plant Loss flow: configure -> review -> confirm -> success", async () => {
    stubFetch();
    render(withQueryClient(<LeafyProductionPage />));
    await waitFor(() => expect(screen.getByText("PP-001 — ICE-0142")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /record plant loss/i }));

    await waitFor(() => expect(screen.getByLabelText(/plant loss count/i)).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText(/plant loss count/i), { target: { value: "5" } });
    fireEvent.change(screen.getByLabelText(/^reason$/i), { target: { value: "dead" } });
    fireEvent.change(screen.getByLabelText(/^date$/i), { target: { value: "2026-08-22" } });
    fireEvent.change(screen.getByLabelText(/^time$/i), { target: { value: "09:00" } });
    fireEvent.click(screen.getByRole("button", { name: "Review" }));

    await waitFor(() => expect(screen.getByText("Review before recording")).toBeInTheDocument());
    expect(screen.getByText("175")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));

    await waitFor(() => expect(screen.getByText("Plant loss recorded")).toBeInTheDocument());
    expect(screen.getByText("175")).toBeInTheDocument();
  });

  it("blocks Review with an over-loss client-side warning", async () => {
    stubFetch();
    render(withQueryClient(<LeafyProductionPage />));
    await waitFor(() => expect(screen.getByText("PP-001 — ICE-0142")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /record plant loss/i }));
    await waitFor(() => expect(screen.getByLabelText(/plant loss count/i)).toBeInTheDocument());

    fireEvent.change(screen.getByLabelText(/plant loss count/i), { target: { value: "200" } });
    fireEvent.change(screen.getByLabelText(/^reason$/i), { target: { value: "dead" } });
    fireEvent.change(screen.getByLabelText(/^date$/i), { target: { value: "2026-08-22" } });
    fireEvent.change(screen.getByLabelText(/^time$/i), { target: { value: "09:00" } });
    fireEvent.click(screen.getByRole("button", { name: "Review" }));

    await waitFor(() => expect(screen.getByText(/exceeds current living population/i)).toBeInTheDocument());
    expect(screen.queryByText("Review before recording")).not.toBeInTheDocument();
  });

  it("requires a note when reason is Other", async () => {
    stubFetch();
    render(withQueryClient(<LeafyProductionPage />));
    await waitFor(() => expect(screen.getByText("PP-001 — ICE-0142")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /record plant loss/i }));
    await waitFor(() => expect(screen.getByLabelText(/plant loss count/i)).toBeInTheDocument());

    fireEvent.change(screen.getByLabelText(/plant loss count/i), { target: { value: "5" } });
    fireEvent.change(screen.getByLabelText(/^reason$/i), { target: { value: "other" } });
    fireEvent.change(screen.getByLabelText(/^date$/i), { target: { value: "2026-08-22" } });
    fireEvent.change(screen.getByLabelText(/^time$/i), { target: { value: "09:00" } });
    fireEvent.click(screen.getByRole("button", { name: "Review" }));

    await waitFor(() => expect(screen.getByText(/note is required when reason is other/i)).toBeInTheDocument());
  });

  it("shows zero-result wording without implying the Plate was moved or sanitized", async () => {
    stubFetch({
      recordResult: {
        command_id: "cmd-1", client_command_id: "x", batch_carrier_assignment_id: "bca-2",
        population_root_batch_carrier_assignment_id: "bca-2", event: HISTORY[0].events[0],
        previous_living_population: 5, resulting_living_population: 0, assignment_released: true,
      },
    });
    render(withQueryClient(<LeafyProductionPage />));
    await waitFor(() => expect(screen.getByText("PP-001 — ICE-0142")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /record plant loss/i }));
    await waitFor(() => expect(screen.getByLabelText(/plant loss count/i)).toBeInTheDocument());

    fireEvent.change(screen.getByLabelText(/plant loss count/i), { target: { value: "5" } });
    fireEvent.change(screen.getByLabelText(/^reason$/i), { target: { value: "dead" } });
    fireEvent.change(screen.getByLabelText(/^date$/i), { target: { value: "2026-08-22" } });
    fireEvent.change(screen.getByLabelText(/^time$/i), { target: { value: "09:00" } });
    fireEvent.click(screen.getByRole("button", { name: "Review" }));
    await waitFor(() => expect(screen.getByText("Review before recording")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));

    await waitFor(() => expect(screen.getByText("Plant loss recorded")).toBeInTheDocument());
    expect(screen.getByText(/Biological assignment released/i)).toBeInTheDocument();
    expect(screen.getByText(/has not been moved, sanitized, or marked available/i)).toBeInTheDocument();
  });

  it("on a 409 conflict, preserves the draft, refreshes population, and forces back to Configure", async () => {
    let activePlatesCalls = 0;
    let recordCalls = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.includes("/leafy-production/active-plates")) {
          activePlatesCalls += 1;
          // Second (post-conflict, invalidation-triggered) fetch reflects a
          // concurrent loss that already happened elsewhere.
          const living = activePlatesCalls === 1 ? 180 : 170;
          return jsonResponse([{ ...ACTIVE_PLATES[0], current_living_population: living }]);
        }
        if (url.includes("/leafy-production/dispositions") && init?.method === "POST") {
          recordCalls += 1;
          if (recordCalls === 1) return jsonResponse({ detail: "conflicts with existing data" }, 409);
          return jsonResponse({
            command_id: "cmd-1", client_command_id: "x", batch_carrier_assignment_id: "bca-1",
            population_root_batch_carrier_assignment_id: "bca-1", event: HISTORY[0].events[0],
            previous_living_population: 170, resulting_living_population: 165, assignment_released: false,
          });
        }
        if (url.includes("/leafy-production/dispositions")) return jsonResponse(HISTORY);
        return jsonResponse([]);
      }),
    );

    render(withQueryClient(<LeafyProductionPage />));
    await waitFor(() => expect(screen.getByText("PP-001 — ICE-0142")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /record plant loss/i }));

    await waitFor(() => expect(screen.getByLabelText(/plant loss count/i)).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText(/plant loss count/i), { target: { value: "5" } });
    fireEvent.change(screen.getByLabelText(/^reason$/i), { target: { value: "dead" } });
    fireEvent.change(screen.getByLabelText(/^date$/i), { target: { value: "2026-08-22" } });
    fireEvent.change(screen.getByLabelText(/^time$/i), { target: { value: "09:00" } });
    fireEvent.click(screen.getByRole("button", { name: "Review" }));
    await waitFor(() => expect(screen.getByText("Review before recording")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));

    // Forced back to Configure -- never a straight retry from a stale Review.
    await waitFor(() => expect(screen.queryByText("Review before recording")).not.toBeInTheDocument());
    await waitFor(() => expect(screen.getByLabelText(/plant loss count/i)).toBeInTheDocument());
    // Draft preserved.
    expect(screen.getByLabelText(/plant loss count/i)).toHaveValue(5);
    // Population refreshed from the invalidated query.
    await waitFor(() => expect(screen.getByText("170")).toBeInTheDocument());
    expect(screen.getByRole("alert")).toBeInTheDocument();
  });

  it("shows Plant Loss History with a released lineage still discoverable", async () => {
    const releasedHistory = [
      { ...HISTORY[0], is_active: false, current_living_population: 0 },
    ];
    stubFetch({ history: releasedHistory });
    render(withQueryClient(<LeafyProductionPage />));
    await waitFor(() => expect(screen.getByText("PP-001 — ICE-0142")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("tab", { name: /plant loss history/i }));

    await waitFor(() => expect(screen.getByText(/Released/)).toBeInTheDocument());
    expect(screen.getByText(/Loss 5/)).toBeInTheDocument();
  });

  it("BROWSER QA CORRECTION 2: renders REDUCTION as Loss and REVERSAL as Restored (never 'Reversal 0')", async () => {
    // Exact PP-QA-2 shape: original -5 Dead REDUCTION (now corrected), plus
    // the +5 Dead REVERSAL that restored it. `plant_loss_quantity` is 0 on
    // the REVERSAL row (a REDUCTION-only field) -- the display must use
    // `quantity_delta` itself, never that field, for the REVERSAL's own
    // magnitude.
    const correctedHistory = [
      {
        population_root_batch_carrier_assignment_id: "bca-2", plate_code: "PP-002", batch_id: "batch-1",
        batch_code: "ICE-0142", opening_population: 5, current_living_population: 5, is_active: true,
        events: [
          {
            id: "evt-1", command_id: "cmd-1", batch_carrier_assignment_id: "bca-2-old",
            population_root_batch_carrier_assignment_id: "bca-2", event_kind: "REDUCTION", reason_code: "dead",
            quantity_delta: -5, plant_loss_quantity: 5, effective_time: "2026-08-20T10:00:00Z",
            recorded_at: "2026-08-20T10:00:00Z", note: null, reverses_event_id: null, corrects_event_id: null,
            is_reversed: true, actor_user_id: "user-1",
          },
          {
            id: "evt-2", command_id: "cmd-2", batch_carrier_assignment_id: "bca-2-old",
            population_root_batch_carrier_assignment_id: "bca-2", event_kind: "REVERSAL", reason_code: "dead",
            quantity_delta: 5, plant_loss_quantity: 0, effective_time: "2026-08-20T10:00:00Z",
            recorded_at: "2026-08-20T11:00:00Z", note: null, reverses_event_id: "evt-1", corrects_event_id: null,
            is_reversed: false, actor_user_id: "user-1",
          },
        ],
      },
    ];
    stubFetch({ history: correctedHistory });
    render(withQueryClient(<LeafyProductionPage />));
    await waitFor(() => expect(screen.getByText("PP-001 — ICE-0142")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("tab", { name: /plant loss history/i }));

    // Original REDUCTION: immutable, still shown as "Loss 5 — Dead",
    // marked corrected.
    await waitFor(() => expect(screen.getByText(/Loss 5 — Dead/)).toBeInTheDocument());
    expect(screen.getByText(/Corrected — see reversal below/)).toBeInTheDocument();

    // REVERSAL: "Restored 5 — Dead", never "Reversal 0" or "Reversal 5".
    expect(screen.getByText(/Restored 5 — Dead/)).toBeInTheDocument();
    expect(screen.queryByText(/Reversal/)).not.toBeInTheDocument();
  });

  it("BROWSER QA CORRECTION 2: a pure-reversal (void) lineage stays structurally intact", async () => {
    const voidHistory = [
      {
        population_root_batch_carrier_assignment_id: "bca-1", plate_code: "PP-001", batch_id: "batch-1",
        batch_code: "ICE-0142", opening_population: 180, current_living_population: 180, is_active: true,
        events: [
          {
            id: "evt-1", command_id: "cmd-1", batch_carrier_assignment_id: "bca-1",
            population_root_batch_carrier_assignment_id: "bca-1", event_kind: "REDUCTION", reason_code: "dead",
            quantity_delta: -5, plant_loss_quantity: 5, effective_time: "2026-08-20T10:00:00Z",
            recorded_at: "2026-08-20T10:00:00Z", note: null, reverses_event_id: null, corrects_event_id: null,
            is_reversed: true, actor_user_id: "user-1",
          },
          {
            id: "evt-2", command_id: "cmd-2", batch_carrier_assignment_id: "bca-1",
            population_root_batch_carrier_assignment_id: "bca-1", event_kind: "REVERSAL", reason_code: "dead",
            quantity_delta: 5, plant_loss_quantity: 0, effective_time: "2026-08-20T10:00:00Z",
            recorded_at: "2026-08-20T11:00:00Z", note: null, reverses_event_id: "evt-1", corrects_event_id: null,
            is_reversed: false, actor_user_id: "user-1",
          },
        ],
      },
    ];
    stubFetch({ history: voidHistory });
    render(withQueryClient(<LeafyProductionPage />));
    await waitFor(() => expect(screen.getByText("PP-001 — ICE-0142")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("tab", { name: /plant loss history/i }));

    await waitFor(() => expect(screen.getByText(/Loss 5 — Dead/)).toBeInTheDocument());
    expect(screen.getByText(/Restored 5 — Dead/)).toBeInTheDocument();
    // Both events remain visible -- a void correction never hides the
    // original entry, and population is back to opening (180).
    expect(screen.getByText(/Current 180/)).toBeInTheDocument();
  });

  it("allows submitting a correction from history", async () => {
    stubFetch();
    render(withQueryClient(<LeafyProductionPage />));
    await waitFor(() => expect(screen.getByText("PP-001 — ICE-0142")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("tab", { name: /plant loss history/i }));
    await waitFor(() => expect(screen.getByText(/Loss 5/)).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "Correct" }));
    await waitFor(() => expect(screen.getByText(/pure reversal/i)).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Submit correction" }));
    await waitFor(() => expect(screen.queryByText(/pure reversal/i)).not.toBeInTheDocument());
  });
});

// --- LEAFY-OPS-002 -----------------------------------------------------------
// "Move plate": a compact physical relocation of an existing Production
// Cultivation Plate between Leafy Tables, reusing the generic Movement
// command unchanged. Fixture ids here are deliberately real UUID-shaped
// (unlike the plain "loc-1"/"carrier-1" ids used above) so the "never a raw
// UUID exposed" assertions are genuine, mirroring the same convention
// established for `vines-production/harvest/page.test.tsx`.

const UUID_PATTERN = /[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}/;

const MOVE_CARRIER_ID = "1a2b3c4d-5e6f-4a1b-8c2d-3e4f5a6b7c8d";
const MOVE_BCA_ID = "9d5b1b8a-6f1e-4b8a-9c2e-9a2b3c4d5e6f";
const MOVE_GH_ID = "3c4d5e6f-7a8b-4c3d-8e4f-5a6b7c8d9e0f";
const MOVE_ZONE_ID = "4d5e6f7a-8b9c-4d4e-9f5a-6b7c8d9e0f1a";
const MOVE_SPAN_ID = "5e6f7a8b-9c0d-4e5f-8a6b-7c8d9e0f1a2b";
const CURRENT_TABLE_ID = "6f7a8b9c-0d1e-4f6a-9b7c-8d9e0f1a2b3c";
const DEST_TABLE_ID = "7a8b9c0d-1e2f-4a7b-8c8d-9e0f1a2b3c4d";

const MOVE_PLATE = {
  carrier_id: MOVE_CARRIER_ID, plate_code: "PP-900", batch_carrier_assignment_id: MOVE_BCA_ID,
  population_root_batch_carrier_assignment_id: MOVE_BCA_ID, batch_id: "batch-900", batch_code: "ICE-0900",
  crop_common_name: "Iceberg Lettuce", variety_name: "Mamutik", opening_population: 100,
  current_living_population: 100, total_recorded_loss: 0,
  current_location: {
    id: CURRENT_TABLE_ID, code: "TA01", name: "TA01", location_type_code: "grow_table",
    ancestry_label: "LEAFY-01 / Z01 / S01 / TA01",
  },
  has_location_warning: false,
};

const ZERO_COUNTS = {
  zones: 1, spans: 1, tables: 2, gutters: 0, bag_positions: 0, seeding_stations: 0, germination_chambers: 0,
  seedling_tables: 0, intersalads_tables: 0, intervines_tables: 0, trolleys: 0, trolley_levels: 0,
  trolley_slots: 0, seeding_machines: 0,
};
const MOVE_OVERVIEW = [
  { greenhouse_id: MOVE_GH_ID, code: "LEAFY-01", name: "Leafy", classification: "leafy_greens", status: "configured", counts: ZERO_COUNTS },
];
const MOVE_STRUCTURE = {
  greenhouse_id: MOVE_GH_ID, code: "LEAFY-01", name: "Leafy", classification: "leafy_greens",
  leafy_zones: [
    {
      id: MOVE_ZONE_ID, code: "Z01",
      spans: [
        {
          id: MOVE_SPAN_ID, code: "S01",
          tables: [
            { id: CURRENT_TABLE_ID, code: "TA01", capacity: 2 },
            { id: DEST_TABLE_ID, code: "TA02", capacity: 2 },
          ],
        },
      ],
    },
  ],
};
const MOVE_PATH = {
  location_id: CURRENT_TABLE_ID,
  path: [
    { id: MOVE_GH_ID, code: "LEAFY-01", name: "Leafy" },
    { id: MOVE_ZONE_ID, code: "Z01", name: "Z01" },
    { id: MOVE_SPAN_ID, code: "S01", name: "S01" },
    { id: CURRENT_TABLE_ID, code: "TA01", name: "TA01" },
  ],
  path_string: "LEAFY-01 / Z01 / S01 / TA01",
};

const MOVEMENT_RESULT = {
  id: "movement-1", tenant_id: "tenant-1", farm_id: "farm-1",
  occupant: { kind: "carrier", id: MOVE_CARRIER_ID },
  source: { kind: "location", id: CURRENT_TABLE_ID },
  destination: { kind: "location", id: DEST_TABLE_ID },
  command_type: "movement", client_command_id: "cmd-move-1",
  effective_time: "2026-09-01T10:00:00Z", recorded_time: "2026-09-01T10:00:00Z",
  actor_user_id: "user-1", reason: null,
};

function stubFetchForMove(overrides: Record<string, unknown> = {}) {
  const movementBodies: unknown[] = [];
  let activePlatesCalls = 0;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.includes("/leafy-production/active-plates")) {
        activePlatesCalls += 1;
        if (overrides.activePlatesAfterMove && activePlatesCalls > 1) {
          return jsonResponse([overrides.activePlatesAfterMove]);
        }
        return jsonResponse(overrides.activePlates ?? [MOVE_PLATE]);
      }
      if (url.includes("/leafy-production/dispositions")) return jsonResponse([]);
      if (url.includes(`/farm-setup/greenhouses/${MOVE_GH_ID}`)) return jsonResponse(MOVE_STRUCTURE);
      if (url.includes("/farm-setup/greenhouses")) return jsonResponse(MOVE_OVERVIEW);
      if (url.includes(`/locations/${CURRENT_TABLE_ID}/path`)) return jsonResponse(MOVE_PATH);
      if (url.includes("/movements") && init?.method === "POST") {
        movementBodies.push(init.body ? JSON.parse(String(init.body)) : null);
        if (overrides.movementError) return jsonResponse({ detail: String(overrides.movementError) }, 409);
        return jsonResponse(MOVEMENT_RESULT);
      }
      return jsonResponse([]);
    }),
  );
  return { getMovementBodies: () => movementBodies };
}

async function openMoveForm() {
  render(withQueryClient(<LeafyProductionPage />));
  await waitFor(() => expect(screen.getByText("PP-900 — ICE-0900")).toBeInTheDocument());
  fireEvent.click(screen.getByRole("button", { name: /move plate/i }));
  await waitFor(() => expect(screen.getByText("Move plate — PP-900")).toBeInTheDocument());
}

async function pickDestinationTable() {
  // The destination Greenhouse/Zone/Span prefill (from the async Location
  // path read) must resolve -- and the Table field become enabled -- before
  // focusing it; firing focus while it's still disabled is a silently
  // ignored event, never replayed once the field later enables.
  await waitFor(() => expect(screen.getByLabelText(/^Table$/i)).not.toBeDisabled());
  fireEvent.focus(screen.getByLabelText(/^Table$/i));
  const listbox = await screen.findByRole("listbox");
  await waitFor(() => expect(within(listbox).getByText("TA02")).toBeInTheDocument());
  fireEvent.click(within(listbox).getByText("TA02"));
}

describe("Move plate", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("renders operator-friendly current placement with a Move plate action, no UUIDs", async () => {
    stubFetchForMove();
    render(withQueryClient(<LeafyProductionPage />));
    await waitFor(() => expect(screen.getByText("PP-900 — ICE-0900")).toBeInTheDocument());
    expect(screen.getByText("LEAFY-01 / Z01 / S01 / TA01")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /move plate/i })).toBeEnabled();
    expect(document.body.textContent).not.toMatch(UUID_PATTERN);
  });

  it("Move plate opens a compact relocation form", async () => {
    stubFetchForMove();
    await openMoveForm();
    expect(screen.getByText("Move to")).toBeInTheDocument();
    expect(screen.getByLabelText(/^Table$/i)).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(UUID_PATTERN);
  });

  it("excludes the current Table from destination options", async () => {
    stubFetchForMove();
    await openMoveForm();
    await waitFor(() => expect(screen.getByLabelText(/^Table$/i)).not.toBeDisabled());
    fireEvent.focus(screen.getByLabelText(/^Table$/i));
    const listbox = await screen.findByRole("listbox");
    await waitFor(() => expect(within(listbox).getByText("TA02")).toBeInTheDocument());
    expect(within(listbox).queryByText("TA01")).not.toBeInTheDocument();
  });

  it("submits a Movement with the correct occupant/destination on Confirm move", async () => {
    const { getMovementBodies } = stubFetchForMove();
    await openMoveForm();
    await pickDestinationTable();

    fireEvent.click(screen.getByRole("button", { name: /review move/i }));
    await waitFor(() => expect(screen.getByText("Review move")).toBeInTheDocument());
    expect(screen.getByText(/TA01 → LEAFY-01 \/ Z01 \/ S01 \/ TA02/)).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(UUID_PATTERN);

    fireEvent.click(screen.getByRole("button", { name: /confirm move/i }));
    await waitFor(() => expect(getMovementBodies()).toHaveLength(1));
    const body = getMovementBodies()[0] as {
      occupant: { kind: string; id: string };
      destination: { kind: string; id: string };
      client_command_id: string;
    };
    expect(body.occupant).toEqual({ kind: "carrier", id: MOVE_CARRIER_ID });
    expect(body.destination).toEqual({ kind: "location", id: DEST_TABLE_ID });
    expect(body.client_command_id).toBeTruthy();
  });

  it("refreshes current placement after a successful move", async () => {
    stubFetchForMove({
      activePlatesAfterMove: {
        ...MOVE_PLATE,
        current_location: {
          id: DEST_TABLE_ID, code: "TA02", name: "TA02", location_type_code: "grow_table",
          ancestry_label: "LEAFY-01 / Z01 / S01 / TA02",
        },
      },
    });
    await openMoveForm();
    await pickDestinationTable();
    fireEvent.click(screen.getByRole("button", { name: /review move/i }));
    await waitFor(() => expect(screen.getByText("Review move")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /confirm move/i }));

    await waitFor(() => expect(screen.getByText("Plate moved")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Done" }));
    await waitFor(() => expect(screen.getByText("LEAFY-01 / Z01 / S01 / TA02")).toBeInTheDocument());
  });

  it("shows a friendly error (never a raw id) on conflict, preserving the selected destination", async () => {
    stubFetchForMove({ movementError: DEST_TABLE_ID });
    await openMoveForm();
    await pickDestinationTable();
    fireEvent.click(screen.getByRole("button", { name: /review move/i }));
    await waitFor(() => expect(screen.getByText("Review move")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /confirm move/i }));

    // Forced back to Configure on conflict -- never a straight retry from a
    // stale Review. ("Review move" is also the Configure step's own button
    // label, so this checks the Review step's heading specifically.)
    await waitFor(() => expect(screen.queryByRole("heading", { name: "Review move" })).not.toBeInTheDocument());
    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
    expect(screen.getByRole("alert").textContent ?? "").not.toMatch(UUID_PATTERN);
    // Destination selection preserved, never reset back to blank.
    expect(screen.getByText("LEAFY-01 / Z01 / S01 / TA02")).toBeInTheDocument();
  });

  it("never renders a raw UUID anywhere across the Move plate flow", async () => {
    stubFetchForMove();
    await openMoveForm();
    expect(document.body.textContent).not.toMatch(UUID_PATTERN);
    await pickDestinationTable();
    fireEvent.click(screen.getByRole("button", { name: /review move/i }));
    await waitFor(() => expect(screen.getByText("Review move")).toBeInTheDocument());
    expect(document.body.textContent).not.toMatch(UUID_PATTERN);
  });
});
