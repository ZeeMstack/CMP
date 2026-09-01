import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { withQueryClient } from "@/lib/test-utils";

import LeafyHarvestPage from "./page";

vi.mock("next/navigation", () => ({
  useParams: () => ({ farmId: "farm-1" }),
}));

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const PLATE_A = {
  production_plate_id: "carrier-1", production_plate_code: "PP-001", batch_id: "batch-1", batch_code: "ICE-0142",
  crop_common_name: "Iceberg Lettuce", variety_name: "Mamutik", current_living_heads: 180,
  current_batch_carrier_assignment_id: "bca-1",
  location: {
    greenhouse: { id: "gh-1", code: "LEAFY-01", name: "Leafy 01" }, zone: { id: "z-1", code: "Z01", name: "Zone 1" },
    span: { id: "s-1", code: "S01", name: "Span 1" }, grow_table: { id: "t-1", code: "TA01", name: "Table 01" },
  },
  has_location_warning: false, quality_hold_open: false,
};

const PLATE_B = {
  production_plate_id: "carrier-2", production_plate_code: "PP-002", batch_id: "batch-1", batch_code: "ICE-0142",
  crop_common_name: "Iceberg Lettuce", variety_name: "Mamutik", current_living_heads: 100,
  current_batch_carrier_assignment_id: "bca-2", location: null, has_location_warning: true, quality_hold_open: false,
};

const PLATE_OTHER_BATCH = {
  production_plate_id: "carrier-3", production_plate_code: "PP-003", batch_id: "batch-2", batch_code: "ICE-0200",
  crop_common_name: "Iceberg Lettuce", variety_name: null, current_living_heads: 50,
  current_batch_carrier_assignment_id: "bca-3", location: null, has_location_warning: true, quality_hold_open: false,
};

const PLATE_HELD = {
  production_plate_id: "carrier-4", production_plate_code: "PP-004", batch_id: "batch-3", batch_code: "ICE-0300",
  crop_common_name: "Iceberg Lettuce", variety_name: null, current_living_heads: 20,
  current_batch_carrier_assignment_id: "bca-4", location: null, has_location_warning: true, quality_hold_open: true,
};

function sourceLine(overrides: Record<string, unknown> = {}) {
  return {
    id: "line-1", batch_carrier_assignment_id: "bca-1",
    carrier: { id: "carrier-1", code: "PP-001", carrier_type: { id: "ct-1", code: "production_cultivation_plate", name: "Production Plate" } },
    harvest_location: {
      greenhouse: { id: "gh-1", code: "LEAFY-01", name: "Leafy 01" }, zone: { id: "z-1", code: "Z01", name: "Zone 1" },
      span: { id: "s-1", code: "S01", name: "Span 1" }, grow_table: { id: "t-1", code: "TA01", name: "Table 01" },
    },
    original_harvested_weight_kg: "2.5", original_whole_unit_count: 5,
    current_harvested_weight_kg: "2.5", current_whole_unit_count: 5, state: "ACTIVE",
    correction_tip_id: null, correction_history: [],
    ...overrides,
  };
}

function harvestEvent(overrides: Record<string, unknown> = {}) {
  return {
    id: "evt-1", tenant_id: "tenant-1", farm_id: "farm-1", batch_id: "batch-1", batch_code: "ICE-0142",
    crop: { id: "crop-1", code: "ICE", common_name: "Iceberg Lettuce" }, variety: null,
    effective_time: "2026-08-20T10:00:00Z", recorded_time: "2026-08-20T10:00:00Z", actor_user_id: "user-1",
    produce_lot_id: "lot-1", produce_lot_code: "HL-ABC12345", note: null,
    original_total_harvested_weight_kg: "2.5", original_total_whole_unit_count: 5,
    current_total_harvested_weight_kg: "2.5", current_total_whole_unit_count: 5,
    available_balance_weight_kg: "2.5", available_balance_whole_unit_count: 5,
    source_lines: [sourceLine()],
    ...overrides,
  };
}

function stubFetch(overrides: Record<string, unknown> = {}) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      if (url.includes("/correct") && method === "POST") {
        if (overrides.correctError) {
          const detail = overrides.correctErrorCode
            ? { message: String(overrides.correctError), code: String(overrides.correctErrorCode) }
            : String(overrides.correctError);
          return jsonResponse({ detail }, (overrides.correctStatus as number) ?? 409);
        }
        return jsonResponse(overrides.correctResult ?? harvestEvent({ source_lines: [sourceLine({ current_whole_unit_count: 4, current_harvested_weight_kg: "2.0", correction_tip_id: "corr-1" })] }));
      }
      if (url.includes("/leafy-production/harvests") && method === "POST") {
        if (overrides.recordError) return jsonResponse({ detail: "conflict" }, 409);
        return jsonResponse(overrides.recordResult ?? harvestEvent());
      }
      if (url.includes("/leafy-production/harvestable-plates")) {
        return jsonResponse(overrides.plates ?? [PLATE_A]);
      }
      if (url.includes("/leafy-production/harvests")) {
        return jsonResponse(overrides.events ?? [harvestEvent()]);
      }
      return jsonResponse([]);
    }),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("LeafyHarvestPage", () => {
  it("renders the Harvestable Plates list with location breakdown", async () => {
    stubFetch();
    render(withQueryClient(<LeafyHarvestPage />));
    await waitFor(() => expect(screen.getByText("PP-001 — ICE-0142")).toBeInTheDocument());
    expect(screen.getByText(/Living 180/)).toBeInTheDocument();
    expect(screen.getByText("LEAFY-01 / Z01 / S01 / TA01")).toBeInTheDocument();
  });

  it("breadcrumbs directly under its own grouped-nav parent (Harvest & Post-Harvest), with no intermediate Leafy Production hop", async () => {
    stubFetch();
    render(withQueryClient(<LeafyHarvestPage />));
    await waitFor(() => expect(screen.getByText("PP-001 — ICE-0142")).toBeInTheDocument());
    expect(screen.getByText("Harvest & Post-Harvest")).toBeInTheDocument();
    expect(screen.queryByText("Leafy Production")).not.toBeInTheDocument();
    expect(screen.queryByText("Batches")).not.toBeInTheDocument();
  });

  it("shows a quality-held Plate visibly, flagged, and not selectable", async () => {
    stubFetch({ plates: [PLATE_HELD] });
    render(withQueryClient(<LeafyHarvestPage />));
    await waitFor(() => expect(screen.getByText("PP-004 — ICE-0300")).toBeInTheDocument());
    expect(screen.getByText("On quality hold — Harvest blocked")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /add to harvest/i })).toBeDisabled();
  });

  it("locks the Batch after the first Plate and disables an incompatible Plate", async () => {
    stubFetch({ plates: [PLATE_A, PLATE_B, PLATE_OTHER_BATCH] });
    render(withQueryClient(<LeafyHarvestPage />));
    await waitFor(() => expect(screen.getByText("PP-001 — ICE-0142")).toBeInTheDocument());

    const addButtons = screen.getAllByRole("button", { name: /add to harvest/i });
    fireEvent.click(addButtons[0]);

    await waitFor(() => expect(screen.getByText(/Record Harvest — ICE-0142/)).toBeInTheDocument());
    // PP-001 is now in the draft (Remove button); PP-002 (same Batch) still addable; PP-003 (other Batch) disabled.
    expect(screen.getByRole("button", { name: /remove from harvest/i })).toBeInTheDocument();
    const otherBatchRow = screen.getByText("PP-003 — ICE-0200").closest("li");
    expect(otherBatchRow).not.toBeNull();
    expect(
      (otherBatchRow as HTMLElement).querySelector("button[disabled]"),
    ).toBeTruthy();
  });

  it("supports multi-Plate entry with independent inputs and shows totals in Review", async () => {
    stubFetch({ plates: [PLATE_A, PLATE_B] });
    render(withQueryClient(<LeafyHarvestPage />));
    await waitFor(() => expect(screen.getByText("PP-001 — ICE-0142")).toBeInTheDocument());

    fireEvent.click(screen.getAllByRole("button", { name: /add to harvest/i })[0]);
    await waitFor(() => expect(screen.getByText(/Record Harvest/)).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /add to harvest/i }));

    const headsInputs = screen.getAllByLabelText(/heads harvested/i);
    const weightInputs = screen.getAllByLabelText(/raw harvested weight/i);
    expect(headsInputs).toHaveLength(2);
    fireEvent.change(headsInputs[0], { target: { value: "5" } });
    fireEvent.change(weightInputs[0], { target: { value: "2.5" } });
    fireEvent.change(headsInputs[1], { target: { value: "3" } });
    fireEvent.change(weightInputs[1], { target: { value: "1.5" } });
    fireEvent.change(screen.getByLabelText(/^date$/i), { target: { value: "2026-08-22" } });
    fireEvent.change(screen.getByLabelText(/^time$/i), { target: { value: "09:00" } });

    fireEvent.click(screen.getByRole("button", { name: "Review" }));
    await waitFor(() => expect(screen.getByText("Review before recording")).toBeInTheDocument());
    expect(screen.getByText("8")).toBeInTheDocument(); // total heads
  });

  it("completes the full Record Harvest flow: configure -> review -> confirm -> success", async () => {
    stubFetch();
    render(withQueryClient(<LeafyHarvestPage />));
    await waitFor(() => expect(screen.getByText("PP-001 — ICE-0142")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /add to harvest/i }));

    await waitFor(() => expect(screen.getByLabelText(/heads harvested/i)).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText(/heads harvested/i), { target: { value: "5" } });
    fireEvent.change(screen.getByLabelText(/raw harvested weight/i), { target: { value: "2.5" } });
    fireEvent.change(screen.getByLabelText(/^date$/i), { target: { value: "2026-08-22" } });
    fireEvent.change(screen.getByLabelText(/^time$/i), { target: { value: "09:00" } });
    fireEvent.click(screen.getByRole("button", { name: "Review" }));

    await waitFor(() => expect(screen.getByText("Review before recording")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));

    await waitFor(() => expect(screen.getByText("Harvest recorded")).toBeInTheDocument());
    expect(screen.getByText("HL-ABC12345")).toBeInTheDocument();
  });

  it("shows the population-release wording without implying the Plate was moved", async () => {
    stubFetch({ plates: [PLATE_A] });
    render(withQueryClient(<LeafyHarvestPage />));
    await waitFor(() => expect(screen.getByText("PP-001 — ICE-0142")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /add to harvest/i }));

    await waitFor(() => expect(screen.getByLabelText(/heads harvested/i)).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText(/heads harvested/i), { target: { value: "180" } });
    fireEvent.change(screen.getByLabelText(/raw harvested weight/i), { target: { value: "90" } });
    fireEvent.change(screen.getByLabelText(/^date$/i), { target: { value: "2026-08-22" } });
    fireEvent.change(screen.getByLabelText(/^time$/i), { target: { value: "09:00" } });
    fireEvent.click(screen.getByRole("button", { name: "Review" }));

    await waitFor(() => expect(screen.getByText(/Production population will be released/)).toBeInTheDocument());
  });

  it("on a 409 conflict, preserves the draft, refreshes plates, and forces back to Configure", async () => {
    let recordCalls = 0;
    let platesCalls = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        const method = init?.method ?? "GET";
        if (url.includes("/leafy-production/harvestable-plates")) {
          platesCalls += 1;
          const heads = platesCalls === 1 ? 180 : 170;
          return jsonResponse([{ ...PLATE_A, current_living_heads: heads }]);
        }
        if (url.includes("/leafy-production/harvests") && method === "POST") {
          recordCalls += 1;
          if (recordCalls === 1) return jsonResponse({ detail: "conflicts with existing data" }, 409);
          return jsonResponse(harvestEvent());
        }
        if (url.includes("/leafy-production/harvests")) return jsonResponse([]);
        return jsonResponse([]);
      }),
    );

    render(withQueryClient(<LeafyHarvestPage />));
    await waitFor(() => expect(screen.getByText("PP-001 — ICE-0142")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /add to harvest/i }));

    await waitFor(() => expect(screen.getByLabelText(/heads harvested/i)).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText(/heads harvested/i), { target: { value: "5" } });
    fireEvent.change(screen.getByLabelText(/raw harvested weight/i), { target: { value: "2.5" } });
    fireEvent.change(screen.getByLabelText(/^date$/i), { target: { value: "2026-08-22" } });
    fireEvent.change(screen.getByLabelText(/^time$/i), { target: { value: "09:00" } });
    fireEvent.click(screen.getByRole("button", { name: "Review" }));
    await waitFor(() => expect(screen.getByText("Review before recording")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));

    await waitFor(() => expect(screen.queryByText("Review before recording")).not.toBeInTheDocument());
    await waitFor(() => expect(screen.getByLabelText(/heads harvested/i)).toBeInTheDocument());
    expect(screen.getByLabelText(/heads harvested/i)).toHaveValue(5);
    await waitFor(() => expect(screen.getByText(/Living 170/)).toBeInTheDocument());
    expect(screen.getByRole("alert")).toBeInTheDocument();
  });

  it("shows Harvest History with original vs. current corrected totals and correction history", async () => {
    stubFetch({
      events: [
        harvestEvent({
          current_total_whole_unit_count: 4, current_total_harvested_weight_kg: "2.0",
          available_balance_whole_unit_count: 3, available_balance_weight_kg: "1.5",
          source_lines: [
            sourceLine({
              current_whole_unit_count: 4, current_harvested_weight_kg: "2.0", correction_tip_id: "corr-1",
              correction_history: [
                {
                  id: "corr-1", supersedes_correction_id: null, is_void: false,
                  corrected_harvested_weight_kg: "2.0", corrected_whole_unit_count: 4, reason_code: "miscounted",
                  note: "Recount", actor_user_id: "user-1", recorded_time: "2026-08-20T12:00:00Z",
                },
              ],
            }),
          ],
        }),
      ],
    });
    render(withQueryClient(<LeafyHarvestPage />));
    await waitFor(() => expect(screen.getByText("PP-001 — ICE-0142")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("tab", { name: /harvest history/i }));

    await waitFor(() => expect(screen.getByText("HL-ABC12345 — ICE-0142")).toBeInTheDocument());
    const originalTotalDd = screen.getByText("Original total").closest("div")?.querySelector("dd");
    expect(originalTotalDd).toHaveTextContent("5 heads / 2.5 kg");
    const currentTotalDd = screen.getByText("Current corrected total").closest("div")?.querySelector("dd");
    expect(currentTotalDd).toHaveTextContent("4 heads / 2.0 kg");
    expect(screen.getByText(/Corrected to 4 heads \/ 2.0 kg/)).toBeInTheDocument();
    // BROWSER QA CORRECTION -- DEFECT 2: the user-facing label, never the raw code.
    expect(screen.getByText(/Miscounted/)).toBeInTheDocument();
    expect(screen.queryByText(/— miscounted \(/)).not.toBeInTheDocument();
  });

  it("BROWSER QA CORRECTION -- DEFECT 2: shows reason labels (not raw codes) for repeated and void corrections", async () => {
    stubFetch({
      events: [
        harvestEvent({
          current_total_whole_unit_count: 3, current_total_harvested_weight_kg: "1.5",
          source_lines: [
            sourceLine({
              current_whole_unit_count: 3, current_harvested_weight_kg: "1.5", correction_tip_id: "corr-2",
              correction_history: [
                {
                  id: "corr-1", supersedes_correction_id: null, is_void: false,
                  corrected_harvested_weight_kg: "2.0", corrected_whole_unit_count: 4, reason_code: "data_entry_error",
                  note: "Typo", actor_user_id: "user-1", recorded_time: "2026-08-20T11:00:00Z",
                },
                {
                  id: "corr-2", supersedes_correction_id: "corr-1", is_void: false,
                  corrected_harvested_weight_kg: "1.5", corrected_whole_unit_count: 3, reason_code: "weighing_error",
                  note: "Scale recalibrated", actor_user_id: "user-1", recorded_time: "2026-08-20T12:00:00Z",
                },
              ],
            }),
          ],
        }),
      ],
    });
    render(withQueryClient(<LeafyHarvestPage />));
    await waitFor(() => expect(screen.getByText("PP-001 — ICE-0142")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("tab", { name: /harvest history/i }));
    await waitFor(() => expect(screen.getByText("HL-ABC12345 — ICE-0142")).toBeInTheDocument());

    expect(screen.getByText(/Data entry error/)).toBeInTheDocument();
    expect(screen.getByText(/Weighing error/)).toBeInTheDocument();
    expect(screen.queryByText(/data_entry_error/)).not.toBeInTheDocument();
    expect(screen.queryByText(/weighing_error/)).not.toBeInTheDocument();
  });

  it("submits a Replace correction from history", async () => {
    stubFetch();
    render(withQueryClient(<LeafyHarvestPage />));
    await waitFor(() => expect(screen.getByText("PP-001 — ICE-0142")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("tab", { name: /harvest history/i }));
    await waitFor(() => expect(screen.getByText("HL-ABC12345 — ICE-0142")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "Correct Harvest" }));
    await waitFor(() => expect(screen.getByText(/Current effective: 5 heads/)).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText(/heads harvested/i), { target: { value: "4" } });
    fireEvent.change(screen.getByLabelText(/raw harvested weight/i), { target: { value: "2.0" } });
    fireEvent.change(screen.getByLabelText(/reason/i), { target: { value: "miscounted" } });
    fireEvent.change(screen.getByLabelText(/note/i), { target: { value: "Recount" } });
    fireEvent.click(screen.getByRole("button", { name: "Review" }));

    await waitFor(() => expect(screen.getByText("Review correction")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Confirm correction" }));
    await waitFor(() => expect(screen.queryByText("Review correction")).not.toBeInTheDocument());
  });

  it("submits a Void correction and shows the VOID state after refetch", async () => {
    stubFetch({
      correctResult: harvestEvent({
        current_total_whole_unit_count: 0, current_total_harvested_weight_kg: "0",
        source_lines: [sourceLine({ current_whole_unit_count: 0, current_harvested_weight_kg: "0", state: "VOID", correction_tip_id: "corr-1" })],
      }),
    });
    render(withQueryClient(<LeafyHarvestPage />));
    await waitFor(() => expect(screen.getByText("PP-001 — ICE-0142")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("tab", { name: /harvest history/i }));
    await waitFor(() => expect(screen.getByText("HL-ABC12345 — ICE-0142")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "Correct Harvest" }));
    await waitFor(() => expect(screen.getByText(/Current effective: 5 heads/)).toBeInTheDocument());
    fireEvent.click(screen.getByLabelText(/void harvest contribution/i));
    fireEvent.change(screen.getByLabelText(/reason/i), { target: { value: "data_entry_error" } });
    fireEvent.change(screen.getByLabelText(/note/i), { target: { value: "Wrong Plate entirely" } });
    fireEvent.click(screen.getByRole("button", { name: "Review" }));

    await waitFor(() => expect(screen.getByText("VOID — 0 heads / 0 kg")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Confirm correction" }));
    await waitFor(() => expect(screen.queryByText("Review correction")).not.toBeInTheDocument());
  });

  it("shows the negative-balance conflict message verbatim, selected via code, never a generic error", async () => {
    stubFetch({
      correctError:
        "this correction would reduce the available Harvest Lot below zero because some quantity has already been consumed in packing",
      correctErrorCode: "HARVEST_NEGATIVE_LOT_BALANCE",
    });
    render(withQueryClient(<LeafyHarvestPage />));
    await waitFor(() => expect(screen.getByText("PP-001 — ICE-0142")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("tab", { name: /harvest history/i }));
    await waitFor(() => expect(screen.getByText("HL-ABC12345 — ICE-0142")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "Correct Harvest" }));
    await waitFor(() => expect(screen.getByText(/Current effective: 5 heads/)).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText(/heads harvested/i), { target: { value: "1" } });
    fireEvent.change(screen.getByLabelText(/raw harvested weight/i), { target: { value: "0.5" } });
    fireEvent.change(screen.getByLabelText(/reason/i), { target: { value: "miscounted" } });
    fireEvent.change(screen.getByLabelText(/note/i), { target: { value: "Correcting down" } });
    fireEvent.click(screen.getByRole("button", { name: "Review" }));
    await waitFor(() => expect(screen.getByText("Review correction")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Confirm correction" }));

    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
    expect(screen.getByText(/already been consumed in packing/i)).toBeInTheDocument();
  });

  it("selects the stale-predecessor branch via error.code, not by parsing message shape/text", async () => {
    // Deliberately NOT a bare UUID, and deliberately NOT the required
    // wording -- if the frontend were still guessing from message shape
    // (the pre-correction-1 UUID-only heuristic), this human text would
    // fail to trigger the stale-predecessor branch. Only `code` may drive it.
    stubFetch({
      correctError: "conflict: predecessor mismatch (internal diagnostic string, not for operators)",
      correctErrorCode: "HARVEST_CORRECTION_STALE",
    });
    render(withQueryClient(<LeafyHarvestPage />));
    await waitFor(() => expect(screen.getByText("PP-001 — ICE-0142")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("tab", { name: /harvest history/i }));
    await waitFor(() => expect(screen.getByText("HL-ABC12345 — ICE-0142")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "Correct Harvest" }));
    await waitFor(() => expect(screen.getByText(/Current effective: 5 heads/)).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText(/heads harvested/i), { target: { value: "4" } });
    fireEvent.change(screen.getByLabelText(/raw harvested weight/i), { target: { value: "2.0" } });
    fireEvent.change(screen.getByLabelText(/reason/i), { target: { value: "miscounted" } });
    fireEvent.change(screen.getByLabelText(/note/i), { target: { value: "Recount" } });
    fireEvent.click(screen.getByRole("button", { name: "Review" }));
    await waitFor(() => expect(screen.getByText("Review correction")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Confirm correction" }));

    await waitFor(() =>
      expect(
        screen.getByText("This Harvest line was corrected by someone else. Refresh and review the latest values before trying again."),
      ).toBeInTheDocument(),
    );
    // The raw diagnostic message must never leak to the operator.
    expect(screen.queryByText(/internal diagnostic string/)).not.toBeInTheDocument();
    // Forced back to the values step, never a stale Review.
    expect(screen.queryByText("Review correction")).not.toBeInTheDocument();
  });

  it("shows the Harvest-time location, distinct from current location, in History", async () => {
    stubFetch();
    render(withQueryClient(<LeafyHarvestPage />));
    await waitFor(() => expect(screen.getByText("PP-001 — ICE-0142")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("tab", { name: /harvest history/i }));
    await waitFor(() => expect(screen.getByText("HL-ABC12345 — ICE-0142")).toBeInTheDocument());
    expect(screen.getByText("Harvested at: LEAFY-01 / Z01 / S01 / TA01")).toBeInTheDocument();
  });

  it("shows an explicit unavailable state when no historical location can be resolved", async () => {
    stubFetch({ events: [harvestEvent({ source_lines: [sourceLine({ harvest_location: null })] })] });
    render(withQueryClient(<LeafyHarvestPage />));
    await waitFor(() => expect(screen.getByText("PP-001 — ICE-0142")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("tab", { name: /harvest history/i }));
    await waitFor(() => expect(screen.getByText("HL-ABC12345 — ICE-0142")).toBeInTheDocument());
    expect(screen.getByText("Harvest-time location unavailable")).toBeInTheDocument();
  });
});
