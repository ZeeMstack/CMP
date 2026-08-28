import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { withQueryClient } from "@/lib/test-utils";

import TraceabilityPage from "./page";

vi.mock("next/navigation", () => ({
  useParams: () => ({ farmId: "farm-1" }),
}));

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const CROP_LETTUCE = { id: "crop-1", code: "LET", common_name: "Lettuce" };

const BATCH_SUMMARY = {
  id: "batch-1", code: "BATCH-001", crop: CROP_LETTUCE, current_stage: { name: "Production" }, state: "active",
};

const HPL = {
  id: "hpl-1", tenant_id: "t", farm_id: "farm-1", code: "HPL-001", crop: CROP_LETTUCE, variety: null,
  harvest_event_id: "he-1", batch_id: "batch-1", total_harvested_weight_kg: "50.000", total_whole_unit_count: null,
  effective_time: "2026-01-01T08:00:00Z", recorded_time: "2026-01-01T08:05:00Z",
};

const GPL = {
  id: "gpl-1", tenant_id: "t", farm_id: "farm-1", grading_event_id: "ge-1", code: "GPL-001", crop: CROP_LETTUCE,
  variety: null, grade_definition_version_id: "gdv-1", original_received_weight_kg: "45.000",
  original_received_whole_unit_count: null, effective_time: "2026-01-02T08:00:00Z", recorded_at: "2026-01-02T08:05:00Z",
};

const FGL = {
  id: "fgl-1", tenant_id: "t", farm_id: "farm-1", code: "FG-001", crop: CROP_LETTUCE, variety: null,
  packing_event_id: "pe-1", source_graded_produce_lot_ids: ["gpl-1"], net_packed_weight_kg: "40.000",
  package_count: 4, effective_time: "2026-01-03T08:00:00Z", recorded_time: "2026-01-03T08:05:00Z",
};

const IMPACT_SUMMARY = {
  affected_crop_batch_count: 1, affected_harvested_produce_lot_count: 1, affected_graded_produce_lot_count: 1,
  affected_finished_goods_lot_count: 1, affected_dispatch_event_count: 0,
  potentially_affected_available_weight_kg: "40.000", potentially_affected_available_package_count: 4,
  potentially_affected_placed_weight_kg: "0", potentially_affected_placed_package_count: 0,
  potentially_affected_unplaced_weight_kg: "40.000", potentially_affected_unplaced_package_count: 4,
  potentially_affected_dispatched_weight_kg: "0", potentially_affected_dispatched_package_count: 0,
};

const COMPLETENESS = { trace_complete: true, limitations: [], capability_limitations: [] };

const CROP_BATCH_IMPACT = {
  subject_batch_id: "batch-1", subject_batch_code: "BATCH-001",
  lineage: { batches: [], edges: [] },
  harvest_events: [{ harvest_event_id: "he-1", batch_id: "batch-1", effective_time: "2026-01-01T08:00:00Z", recorded_time: "2026-01-01T08:05:00Z" }],
  produce_lots: [{ harvested_produce_lot_id: "hpl-1", code: "HPL-001", harvest_event_id: "he-1", batch_id: "batch-1", total_harvested_weight_kg: "50.000", total_whole_unit_count: null, effective_time: "2026-01-01T08:00:00Z" }],
  packing_inputs: [],
  graded_produce_lots: [{ graded_produce_lot_id: "gpl-1", code: "GPL-001", grading_event_id: "ge-1", crop_id: "crop-1", variety_id: null, grade_definition_version_id: "gdv-1", original_received_weight_kg: "45.000", original_received_whole_unit_count: null, effective_time: "2026-01-02T08:00:00Z" }],
  finished_goods: [],
  storage: [],
  dispatches: [],
  summary: IMPACT_SUMMARY,
  completeness: COMPLETENESS,
};

const FGL_TRACE = {
  subject: { finished_goods_lot_id: "fgl-1", code: "FG-001", packing_event_id: "pe-1", net_packed_weight_kg: "40.000", package_count: 4, effective_time: "2026-01-03T08:00:00Z", available_weight_kg: "40.000", available_package_count: 4, placed_weight_kg: "0", placed_package_count: 0, unplaced_weight_kg: "40.000", unplaced_package_count: 4 },
  packing_event: { packing_event_id: "pe-1", total_input_weight_kg: "45.000", packed_output_weight_kg: "40.000", process_loss_weight_kg: "3.000", rejected_weight_kg: "2.000", effective_time: "2026-01-03T08:00:00Z", recorded_time: "2026-01-03T08:05:00Z" },
  packing_inputs: [],
  graded_produce_lots: [{ graded_produce_lot_id: "gpl-1", code: "GPL-001", grading_event_id: "ge-1", crop_id: "crop-1", variety_id: null, grade_definition_version_id: "gdv-1", original_received_weight_kg: "45.000", original_received_whole_unit_count: null, effective_time: "2026-01-02T08:00:00Z" }],
  grading_events: [],
  produce_lots: [{ harvested_produce_lot_id: "hpl-1", code: "HPL-001", harvest_event_id: "he-1", batch_id: "batch-1", total_harvested_weight_kg: "50.000", total_whole_unit_count: null, effective_time: "2026-01-01T08:00:00Z" }],
  harvest_events: [],
  lineage: { batches: [], edges: [] },
  seed_origins: [],
  storage_movements: [],
  dispatches: [],
  quality: [],
  completeness: COMPLETENESS,
};

function stubFetch() {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/traceability/crop-batches/") && url.includes("/impact")) return jsonResponse(CROP_BATCH_IMPACT);
      if (url.includes("/traceability/harvested-produce-lots/") && url.includes("/impact")) return jsonResponse(CROP_BATCH_IMPACT);
      if (url.includes("/traceability/finished-goods-lots/")) return jsonResponse(FGL_TRACE);
      if (url.includes("/crop-batches/operational-summary")) return jsonResponse([BATCH_SUMMARY]);
      if (url.includes("/locations/tree")) return jsonResponse([]);
      if (url.includes("/harvested-produce-lots")) return jsonResponse([HPL]);
      if (url.includes("/graded-produce-lots")) return jsonResponse([GPL]);
      if (url.includes("/finished-goods-lots")) return jsonResponse([FGL]);
      return jsonResponse([]);
    }),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("TraceabilityPage", () => {
  it("renders all four entry-point tabs and starts with an empty state", async () => {
    stubFetch();
    render(withQueryClient(<TraceabilityPage />));

    expect(screen.getByRole("tab", { name: "Crop Batch" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Harvested Produce Lot" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Graded Produce Lot" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Finished Goods Lot" })).toBeInTheDocument();
    expect(screen.getByText("Start a trace")).toBeInTheDocument();
  });

  it("traces from a Crop Batch and shows only read links, with farmId preserved", async () => {
    stubFetch();
    render(withQueryClient(<TraceabilityPage />));

    fireEvent.focus(screen.getByRole("combobox", { name: /select crop batch/i }));
    await waitFor(() => expect(screen.getByText("BATCH-001")).toBeInTheDocument());
    fireEvent.click(screen.getByText("BATCH-001"));

    await waitFor(() => expect(screen.getByText("Harvested Produce Lots (1)")).toBeInTheDocument());
    expect(screen.getByText("HPL-001")).toBeInTheDocument();
    const gplLink = screen.getByRole("link", { name: "GPL-001" });
    expect(gplLink).toHaveAttribute("href", "/farms/farm-1/processing/graded-lots/gpl-1");

    // Read-only: no button anywhere offers to record/edit/reverse anything.
    expect(screen.queryByRole("button", { name: /record|reverse|confirm|delete|edit/i })).not.toBeInTheDocument();
  });

  it("traces from a Finished Goods Lot and reuses the real Packing reconciliation", async () => {
    stubFetch();
    render(withQueryClient(<TraceabilityPage />));

    fireEvent.click(screen.getByRole("tab", { name: "Finished Goods Lot" }));
    fireEvent.focus(screen.getByRole("combobox", { name: /select finished goods lot/i }));
    await waitFor(() => expect(screen.getByText("FG-001")).toBeInTheDocument());
    fireEvent.click(screen.getByText("FG-001"));

    await waitFor(() => expect(screen.getByText("Balanced")).toBeInTheDocument());
    expect(screen.getByRole("link", { name: "FG-001" })).toHaveAttribute("href", "/farms/farm-1/processing/finished-goods/fgl-1");
    expect(screen.getByRole("link", { name: "GPL-001" })).toHaveAttribute("href", "/farms/farm-1/processing/graded-lots/gpl-1");
  });
});
