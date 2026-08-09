import { describe, expect, it } from "vitest";

import { compareStageGroups, groupBatchesByStage } from "./stageOrder";

function batchAtStage(category: string, name: string) {
  return { current_stage: { name, stage_category: category } };
}

describe("compareStageGroups", () => {
  it("orders known categories by the domain's own biological progression, not alphabetically", () => {
    const groups = [
      { category: "harvest_ready", name: "Zulu Phase" },
      { category: "seeding", name: "Seeding" },
      { category: "production", name: "Growing" },
    ];
    const sorted = [...groups].sort(compareStageGroups);
    expect(sorted.map((g) => g.category)).toEqual(["seeding", "production", "harvest_ready"]);
  });

  it("breaks ties within the same category alphabetically by stage name", () => {
    const groups = [
      { category: "production", name: "Zone Growth" },
      { category: "production", name: "Alpha Growth" },
    ];
    const sorted = [...groups].sort(compareStageGroups);
    expect(sorted.map((g) => g.name)).toEqual(["Alpha Growth", "Zone Growth"]);
  });

  it("places an unrecognized category deterministically at the end, never crashing", () => {
    const groups = [
      { category: "some_future_category", name: "Mystery" },
      { category: "seeding", name: "Seeding" },
    ];
    const sorted = [...groups].sort(compareStageGroups);
    expect(sorted.map((g) => g.category)).toEqual(["seeding", "some_future_category"]);
  });
});

describe("groupBatchesByStage", () => {
  it("aggregates batches with the same category and the same stage name into one row", () => {
    const groups = groupBatchesByStage([
      batchAtStage("production", "Growing"),
      batchAtStage("production", "Growing"),
    ]);
    expect(groups).toEqual([{ category: "production", name: "Growing", count: 2 }]);
  });

  it("keeps batches with the same visible stage name but different categories as distinct rows", () => {
    const groups = groupBatchesByStage([
      batchAtStage("nursery", "Growing"),
      batchAtStage("production", "Growing"),
    ]);
    expect(groups).toHaveLength(2);
    expect(groups).toContainEqual({ category: "nursery", name: "Growing", count: 1 });
    expect(groups).toContainEqual({ category: "production", name: "Growing", count: 1 });
  });

  it("never groups by stage ID -- two batches with different current_stage.id but the same (category, name) still aggregate", () => {
    const groups = groupBatchesByStage([
      { current_stage: { name: "Growing", stage_category: "production" } },
      { current_stage: { name: "Growing", stage_category: "production" } },
    ]);
    expect(groups).toEqual([{ category: "production", name: "Growing", count: 2 }]);
  });

  it("never infers category from stage name/code -- a stage coded/named to look harvest-related but categorized otherwise stays under its authoritative category", () => {
    const groups = groupBatchesByStage([
      { current_stage: { name: "Harvest Ready", stage_category: "production" } },
    ]);
    expect(groups).toEqual([{ category: "production", name: "Harvest Ready", count: 1 }]);
  });

  it("returns groups pre-sorted by the domain category order", () => {
    const groups = groupBatchesByStage([
      batchAtStage("harvest_ready", "Zulu Phase"),
      batchAtStage("seeding", "Seeding"),
    ]);
    expect(groups.map((g) => g.category)).toEqual(["seeding", "harvest_ready"]);
  });

  it("returns an empty list for no batches", () => {
    expect(groupBatchesByStage([])).toEqual([]);
  });
});
