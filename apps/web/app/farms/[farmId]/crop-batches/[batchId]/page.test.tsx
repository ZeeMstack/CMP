import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useParams: () => ({ farmId: "farm-1", batchId: "batch-1" }),
  useSearchParams: () => new URLSearchParams("tab=sowing"),
}));

import { withQueryClient } from "@/lib/test-utils";

import CropBatchDetailPage from "./page";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const FARM = { id: "farm-1", tenant_id: "t", code: "F1", name: "Farm 1", country_code: "AE", city_region: null, timezone: "Asia/Dubai" };

const BATCH = {
  id: "batch-1", tenant_id: "t", farm_id: "farm-1", code: "CB-20260814-001",
  workflow: { id: "wf-1", code: "WF", name: "Lettuce Workflow" }, workflow_version_id: "wv-1", version_number: 1,
  crop: { id: "crop-1", code: "ICE", common_name: "Iceberg Lettuce" },
  variety: { id: "var-1", code: "MAM", name: "Mamutik" },
  production_system: { id: "ps-1", code: "PS", name: "Nursery Tray" },
  state: "active", current_stage: { id: "stage-1", code: "SEEDING", name: "Seeding" },
  created_effective_time: "2026-08-14T09:00:00Z", created_at: "2026-08-14T09:00:00Z",
  closed_effective_time: null, superseded_effective_time: null,
  superseded_by_batch_derivation_event_id: null, created_by_batch_derivation_event_id: null,
};

const OPERATIONAL_CONTEXT = {
  id: "batch-1", code: "CB-20260814-001",
  crop: { id: "crop-1", code: "ICE", common_name: "Iceberg Lettuce" },
  variety: { id: "var-1", code: "MAM", name: "Mamutik" },
  state: "active", current_stage: { id: "stage-1", code: "SEEDING", name: "Seeding" },
  sowing_origins: [], sown_effective_time: null,
  placement: { active_carrier_count: 0, placed_carrier_count: 0, unplaced_carrier_count: 0, placements: [], common_ancestor_path: null },
  open_quality_hold_count: 0,
};

const SOWING_EVENTS = [
  {
    id: "sow-1", tenant_id: "t", farm_id: "farm-1", batch_id: "batch-1", batch_code: "CB-20260814-001",
    workflow_version_id: "wv-1", stage: { id: "stage-1", code: "SEEDING", name: "Seeding" },
    effective_time: "2026-08-14T09:00:00Z", recorded_time: "2026-08-14T09:00:05Z",
    actor_user_id: "u-1", client_command_id: "cmd-1", note: null,
    seeding_station: { id: "station-1", code: "SEED-01" },
    seeding_machine: null,
    lines: [
      {
        id: "line-1", batch_carrier_assignment_id: "assign-1",
        carrier: { id: "tray-1", code: "ST-0001", carrier_type: { id: "ct-1", code: "seed_tray", name: "Seed Tray" } },
        seed_lot: { id: "lot-1", code: "RZ-MAM-2026-001" },
        sown_site_count: 200, seed_count: 200, line_note: null,
      },
      {
        id: "line-2", batch_carrier_assignment_id: "assign-2",
        carrier: { id: "tray-2", code: "ST-0002", carrier_type: { id: "ct-1", code: "seed_tray", name: "Seed Tray" } },
        seed_lot: { id: "lot-1", code: "RZ-MAM-2026-001" },
        sown_site_count: 200, seed_count: 200, line_note: null,
      },
    ],
    total_seeds_sown: 400,
  },
];

function stubFetch(overrides: Record<string, unknown> = {}) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/sowings")) return jsonResponse(overrides.sowings ?? SOWING_EVENTS);
      if (url.includes("/operational-context")) return jsonResponse(overrides.operational ?? OPERATIONAL_CONTEXT);
      if (url.includes("/stage-history")) return jsonResponse(overrides.stageHistory ?? []);
      if (url.includes("/lineage")) return jsonResponse(overrides.lineage ?? { parents: [], children: [] });
      if (url.includes("/quality-holds")) return jsonResponse(overrides.qualityHolds ?? []);
      if (url.includes("/crop-batches/batch-1")) return jsonResponse(overrides.batch ?? BATCH);
      if (url.includes("/farms/farm-1")) return jsonResponse(overrides.farm ?? FARM);
      return jsonResponse([]);
    }),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("CropBatchDetailPage Sowing tab", () => {
  it("shows Seed Lot, Seeding Station, total seeds, and tray codes -- with no Germination claims", async () => {
    stubFetch();
    render(withQueryClient(<CropBatchDetailPage />));

    await waitFor(() => expect(screen.getByText("RZ-MAM-2026-001")).toBeInTheDocument());
    expect(screen.getByText("SEED-01")).toBeInTheDocument();
    expect(screen.getByText("400")).toBeInTheDocument();
    expect(screen.getByText("ST-0001")).toBeInTheDocument();
    expect(screen.getByText("ST-0002")).toBeInTheDocument();
    expect(screen.queryByText(/germinat/i)).not.toBeInTheDocument();
  });

  it("shows an honest empty state when the batch has no Sowing record", async () => {
    stubFetch({ sowings: [] });
    render(withQueryClient(<CropBatchDetailPage />));

    await waitFor(() => expect(screen.getByText("No Sowing record")).toBeInTheDocument());
  });
});
