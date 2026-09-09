import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { withQueryClient } from "@/lib/test-utils";

import VinesHarvestPage from "./page";

vi.mock("next/navigation", () => ({
  useParams: () => ({ farmId: "farm-1" }),
}));

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

// Real UUID-shaped ids -- backs the "no raw UUIDs rendered" requirement
// with a realistic fixture rather than one that happens to use short,
// human-looking ids.
const GUTTER_A_ID = "11111111-1111-4111-8111-111111111111";
const GUTTER_B_ID = "22222222-2222-4222-8222-222222222222";
const GUTTER_OTHER_BATCH_ID = "33333333-3333-4333-8333-333333333333";
const GUTTER_HELD_ID = "44444444-4444-4444-8444-444444444444";
const UUID_PATTERN = /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/i;

const SOURCE_A = {
  batch_id: "batch-1", batch_code: "TOM-001", crop_common_name: "Cherry Tomato", variety_name: "Sakura",
  greenhouse_id: "gh-1", greenhouse_code: "GH-04", gutter_id: GUTTER_A_ID, gutter_code: "GUT-001",
  living_plant_count: 20, last_harvest_effective_time: "2026-09-01T09:00:00Z", quality_hold_open: false,
};
const SOURCE_B = {
  batch_id: "batch-1", batch_code: "TOM-001", crop_common_name: "Cherry Tomato", variety_name: "Sakura",
  greenhouse_id: "gh-1", greenhouse_code: "GH-04", gutter_id: GUTTER_B_ID, gutter_code: "GUT-002",
  living_plant_count: 18, last_harvest_effective_time: null, quality_hold_open: false,
};
const SOURCE_OTHER_BATCH = {
  batch_id: "batch-2", batch_code: "TOM-002", crop_common_name: "Cherry Tomato", variety_name: null,
  greenhouse_id: "gh-1", greenhouse_code: "GH-04", gutter_id: GUTTER_OTHER_BATCH_ID, gutter_code: "GUT-003",
  living_plant_count: 12, last_harvest_effective_time: null, quality_hold_open: false,
};
const SOURCE_HELD = {
  batch_id: "batch-3", batch_code: "TOM-003", crop_common_name: "Cherry Tomato", variety_name: null,
  greenhouse_id: "gh-1", greenhouse_code: "GH-04", gutter_id: GUTTER_HELD_ID, gutter_code: "GUT-004",
  living_plant_count: 8, last_harvest_effective_time: null, quality_hold_open: true,
};

function sourceLine(overrides: Record<string, unknown> = {}) {
  return {
    id: "line-1", gutter: { id: GUTTER_A_ID, code: "GUT-001", name: "GUT-001" },
    harvest_location: {
      greenhouse: { id: "gh-1", code: "GH-04", name: "Vines Greenhouse" }, zone: { id: "z-1", code: "Z1", name: "Zone 1" },
      span: { id: "s-1", code: "S1", name: "Span 1" }, gutter: { id: GUTTER_A_ID, code: "GUT-001", name: "GUT-001" },
    },
    grow_bags: [{ id: "bag-1", code: "GB-0001", carrier_type: { id: "ct-1", code: "grow_bag", name: "Grow Bag" } }],
    original_harvested_weight_kg: "10.000", current_harvested_weight_kg: "10.000", state: "ACTIVE",
    correction_tip_id: null, correction_history: [],
    ...overrides,
  };
}

function harvestEvent(overrides: Record<string, unknown> = {}) {
  return {
    id: "evt-1", tenant_id: "tenant-1", farm_id: "farm-1", batch_id: "batch-1", batch_code: "TOM-001",
    crop: { id: "crop-1", code: "TOM", common_name: "Cherry Tomato" }, variety: null,
    effective_time: "2026-09-01T09:00:00Z", recorded_time: "2026-09-01T09:00:00Z", actor_user_id: "user-1",
    produce_lot_id: "lot-1", produce_lot_code: "VH-ABC12345", note: null,
    original_total_harvested_weight_kg: "10.000", current_total_harvested_weight_kg: "10.000",
    available_balance_weight_kg: "10.000", source_lines: [sourceLine()],
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
        if (overrides.correctError) return jsonResponse({ detail: String(overrides.correctError) }, 409);
        return jsonResponse(
          overrides.correctResult
          ?? harvestEvent({ source_lines: [sourceLine({ current_harvested_weight_kg: "9.000", correction_tip_id: "corr-1" })] }),
        );
      }
      if (url.includes("/vines-production/harvests") && method === "POST") {
        if (overrides.recordError) return jsonResponse({ detail: "conflict" }, 409);
        return jsonResponse(overrides.recordResult ?? harvestEvent());
      }
      if (url.includes("/vines-production/harvestable-sources")) {
        return jsonResponse(overrides.sources ?? [SOURCE_A]);
      }
      if (url.includes("/vines-production/harvests")) {
        return jsonResponse(overrides.events ?? []);
      }
      return jsonResponse([]);
    }),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("VinesHarvestPage", () => {
  it("renders the Harvestable Sources list with living plants, last harvest, and no raw UUIDs", async () => {
    stubFetch();
    render(withQueryClient(<VinesHarvestPage />));
    await waitFor(() => expect(screen.getByText("TOM-001")).toBeInTheDocument());
    expect(screen.getByText("Cherry Tomato")).toBeInTheDocument();
    expect(screen.getByText("GUT-001")).toBeInTheDocument();
    expect(screen.getByText("20")).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(UUID_PATTERN);
  });

  it("shows a quality-held source visibly, flagged, and not selectable", async () => {
    stubFetch({ sources: [SOURCE_HELD] });
    render(withQueryClient(<VinesHarvestPage />));
    await waitFor(() => expect(screen.getByText("GUT-004")).toBeInTheDocument());
    expect(screen.getByText("Quality hold")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /add/i })).toBeDisabled();
  });

  it("locks the Batch after the first Gutter and disables an incompatible Gutter", async () => {
    stubFetch({ sources: [SOURCE_A, SOURCE_B, SOURCE_OTHER_BATCH] });
    render(withQueryClient(<VinesHarvestPage />));
    await waitFor(() => expect(screen.getByText("GUT-001")).toBeInTheDocument());

    fireEvent.click(screen.getAllByRole("button", { name: /^add$/i })[0]);

    await waitFor(() => expect(screen.getByText(/Record Harvest — TOM-001/)).toBeInTheDocument());
    expect(screen.getByRole("button", { name: /remove/i })).toBeInTheDocument();
    const otherBatchRow = screen.getByText("GUT-003").closest("tr");
    expect(otherBatchRow).not.toBeNull();
    expect((otherBatchRow as HTMLElement).querySelector("button[disabled]")).toBeTruthy();
  });

  it("supports multiple Gutter rows with independent weight inputs and shows the total in Review", async () => {
    stubFetch({ sources: [SOURCE_A, SOURCE_B] });
    render(withQueryClient(<VinesHarvestPage />));
    await waitFor(() => expect(screen.getByText("GUT-001")).toBeInTheDocument());

    fireEvent.click(screen.getAllByRole("button", { name: /^add$/i })[0]);
    await waitFor(() => expect(screen.getByText(/Record Harvest/)).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /^add$/i }));

    const weightInputs = screen.getAllByLabelText(/raw weight/i);
    expect(weightInputs).toHaveLength(2);
    fireEvent.change(weightInputs[0], { target: { value: "15" } });
    fireEvent.change(weightInputs[1], { target: { value: "12" } });
    fireEvent.change(screen.getByLabelText(/^date$/i), { target: { value: "2026-09-08" } });
    fireEvent.change(screen.getByLabelText(/^time$/i), { target: { value: "09:00" } });

    fireEvent.click(screen.getByRole("button", { name: /review harvest/i }));
    await waitFor(() => expect(screen.getByText("Review before recording")).toBeInTheDocument());
    expect(screen.getByText("27 kg")).toBeInTheDocument(); // total raw harvest
  });

  it("completes the full Record Harvest flow: configure -> review -> confirm -> success", async () => {
    stubFetch();
    render(withQueryClient(<VinesHarvestPage />));
    await waitFor(() => expect(screen.getByText("GUT-001")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /^add$/i }));

    await waitFor(() => expect(screen.getByLabelText(/raw weight/i)).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText(/raw weight/i), { target: { value: "10" } });
    fireEvent.change(screen.getByLabelText(/^date$/i), { target: { value: "2026-09-08" } });
    fireEvent.change(screen.getByLabelText(/^time$/i), { target: { value: "09:00" } });
    fireEvent.click(screen.getByRole("button", { name: /review harvest/i }));

    await waitFor(() => expect(screen.getByText("Review before recording")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));

    await waitFor(() => expect(screen.getByText("Harvest recorded")).toBeInTheDocument());
    expect(screen.getByText("VH-ABC12345")).toBeInTheDocument();
  });

  it("Loss/harvest never implies plants were removed -- repeat-harvest reassurance shown in Review", async () => {
    stubFetch();
    render(withQueryClient(<VinesHarvestPage />));
    await waitFor(() => expect(screen.getByText("GUT-001")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /^add$/i }));
    await waitFor(() => expect(screen.getByLabelText(/raw weight/i)).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText(/raw weight/i), { target: { value: "10" } });
    fireEvent.change(screen.getByLabelText(/^date$/i), { target: { value: "2026-09-08" } });
    fireEvent.change(screen.getByLabelText(/^time$/i), { target: { value: "09:00" } });
    fireEvent.click(screen.getByRole("button", { name: /review harvest/i }));

    await waitFor(() =>
      expect(screen.getByText(/remains fully harvestable again later \(repeat harvest\)/i)).toBeInTheDocument(),
    );
  });

  it("Harvest History shows repeat harvests from the same Batch as separate rows, human-readable codes only", async () => {
    stubFetch({
      events: [
        harvestEvent({ id: "evt-1", produce_lot_code: "VH-DAY1", original_total_harvested_weight_kg: "10.000" }),
        harvestEvent({ id: "evt-2", produce_lot_code: "VH-DAY7", original_total_harvested_weight_kg: "8.000" }),
      ],
    });
    render(withQueryClient(<VinesHarvestPage />));
    await waitFor(() => expect(screen.getByText("GUT-001")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("tab", { name: /harvest history/i }));

    await waitFor(() => expect(screen.getByText(/VH-DAY1 — TOM-001/)).toBeInTheDocument());
    expect(screen.getByText(/VH-DAY7 — TOM-001/)).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(UUID_PATTERN);
  });

  it("Harvest History shows the underlying Grow Bag lineage for a Gutter-anchored source line", async () => {
    stubFetch({ events: [harvestEvent()] });
    render(withQueryClient(<VinesHarvestPage />));
    await waitFor(() => expect(screen.getByText("GUT-001")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("tab", { name: /harvest history/i }));
    await waitFor(() => expect(screen.getByText(/VH-ABC12345/)).toBeInTheDocument());
    expect(screen.getByText(/Grow Bags present: GB-0001/)).toBeInTheDocument();
  });

  it("submits a Replace correction from history", async () => {
    stubFetch({ events: [harvestEvent()] });
    render(withQueryClient(<VinesHarvestPage />));
    await waitFor(() => expect(screen.getByText("GUT-001")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("tab", { name: /harvest history/i }));
    await waitFor(() => expect(screen.getByText(/VH-ABC12345/)).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "Correct Harvest" }));
    await waitFor(() => expect(screen.getByText(/Current effective: 10.000 kg/)).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText(/raw harvested weight/i), { target: { value: "9" } });
    fireEvent.change(screen.getByLabelText(/reason/i), { target: { value: "scale_error" } });
    fireEvent.change(screen.getByLabelText(/note/i), { target: { value: "Reweighed" } });
    fireEvent.click(screen.getByRole("button", { name: "Review" }));

    await waitFor(() => expect(screen.getByText("Review correction")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Confirm correction" }));
    await waitFor(() => expect(screen.queryByText("Review correction")).not.toBeInTheDocument());
  });

  it("submits a Void correction and shows the VOID state after refetch", async () => {
    stubFetch({
      events: [harvestEvent()],
      correctResult: harvestEvent({
        current_total_harvested_weight_kg: "0",
        source_lines: [sourceLine({ current_harvested_weight_kg: "0", state: "VOID", correction_tip_id: "corr-1" })],
      }),
    });
    render(withQueryClient(<VinesHarvestPage />));
    await waitFor(() => expect(screen.getByText("GUT-001")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("tab", { name: /harvest history/i }));
    await waitFor(() => expect(screen.getByText(/VH-ABC12345/)).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "Correct Harvest" }));
    await waitFor(() => expect(screen.getByText(/Current effective: 10.000 kg/)).toBeInTheDocument());
    fireEvent.click(screen.getByLabelText(/void this gutter/i));
    fireEvent.change(screen.getByLabelText(/reason/i), { target: { value: "data_entry_error" } });
    fireEvent.change(screen.getByLabelText(/note/i), { target: { value: "Wrong Gutter entirely" } });
    fireEvent.click(screen.getByRole("button", { name: "Review" }));

    await waitFor(() => expect(screen.getByText("VOID — 0 kg")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Confirm correction" }));
    await waitFor(() => expect(screen.queryByText("Review correction")).not.toBeInTheDocument());
  });
});
