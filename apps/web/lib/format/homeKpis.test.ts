import { describe, expect, it } from "vitest";

import type { BatchOperationalContext } from "@/lib/api/client";

import { computeHomeKpis } from "./homeKpis";

function makeBatch(overrides: Partial<BatchOperationalContext> = {}): BatchOperationalContext {
  return {
    id: "b1",
    code: "BATCH-001",
    crop: { id: "crop-1", code: "LETTUCE", common_name: "Lettuce" },
    variety: null,
    state: "active",
    current_stage: { id: "stage-1", code: "GROW", name: "Growing", is_terminal: false, stage_category: "production" },
    sowing_origins: [],
    sown_effective_time: null,
    placement: { active_carrier_count: 0, placed_carrier_count: 0, unplaced_carrier_count: 0, placements: [], common_ancestor_path: null },
    open_quality_hold_count: 0,
    ...overrides,
  };
}

describe("computeHomeKpis", () => {
  it("counts every batch passed in as an active batch (caller is responsible for state=active filtering)", () => {
    const kpis = computeHomeKpis([makeBatch(), makeBatch({ id: "b2" }), makeBatch({ id: "b3" })]);
    expect(kpis.activeCount).toBe(3);
  });

  it("counts harvest-ready batches by authoritative stage_category, not stage name", () => {
    const batches = [
      makeBatch({ id: "b1", current_stage: { id: "s1", code: "Q7", name: "Zulu Phase", is_terminal: false, stage_category: "harvest_ready" } }),
      makeBatch({ id: "b2", current_stage: { id: "s2", code: "HARVEST", name: "Harvest Ready", is_terminal: false, stage_category: "production" } }),
      makeBatch({ id: "b3", current_stage: { id: "s3", code: "GROW", name: "Growing", is_terminal: false, stage_category: "harvest_ready" } }),
    ];
    const kpis = computeHomeKpis(batches);
    // b1 and b3 are harvest_ready by category; b2 merely *looks* harvest-ready
    // by name/code and must NOT be counted.
    expect(kpis.harvestReadyCount).toBe(2);
  });

  it("counts batches with an open hold, not the sum of individual hold records", () => {
    const batches = [
      makeBatch({ id: "b1", open_quality_hold_count: 1 }),
      makeBatch({ id: "b2", open_quality_hold_count: 3 }),
      makeBatch({ id: "b3", open_quality_hold_count: 0 }),
    ];
    const kpis = computeHomeKpis(batches);
    // 2 batches affected, even though there are 4 individual hold records.
    expect(kpis.openHoldBatchCount).toBe(2);
  });

  it("returns all zeros for an empty batch set", () => {
    expect(computeHomeKpis([])).toEqual({ activeCount: 0, harvestReadyCount: 0, openHoldBatchCount: 0 });
  });
});
