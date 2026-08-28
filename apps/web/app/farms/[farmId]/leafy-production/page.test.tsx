import { fireEvent, render, screen, waitFor } from "@testing-library/react";
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
