import { describe, expect, it } from "vitest";

import {
  segmentForAttention,
  segmentForMine,
  segmentsTotalCount,
  type HomeQueueSources,
} from "./homeQueue";

function baseSources(overrides: Partial<HomeQueueSources> = {}): HomeQueueSources {
  const empty = { data: [], isLoading: false, error: null };
  return {
    myWorkItems: { ...empty },
    harvestablePlates: { ...empty },
    activeBatches: { ...empty },
    cropIssues: { ...empty },
    inspectionsDue: { ...empty },
    waterAttention: { ...empty },
    equipmentAttention: { ...empty },
    blockedWorkItems: { ...empty },
    carryoverWorkItems: { ...empty },
    ...overrides,
  } as HomeQueueSources;
}

describe("segmentForMine", () => {
  it("maps assigned Farm Work Items into one Work Item segment", () => {
    const sources = baseSources({
      myWorkItems: {
        data: [{ id: "wi-1", title: "Check reservoir", due_at: null, crop_batch: null, location: null } as never],
        isLoading: false,
        error: null,
      },
    });
    const segments = segmentForMine(sources);
    expect(segments).toHaveLength(1);
    expect(segments[0].rows).toEqual([
      expect.objectContaining({ id: "work-item:wi-1", sourceLabel: "Work Item", title: "Check reservoir" }),
    ]);
  });
});

describe("segmentForAttention: independent per-source failure isolation", () => {
  it("keeps every other segment's rows visible when one source errors", () => {
    const sources = baseSources({
      activeBatches: { data: [{ id: "b1", code: "B-001", open_quality_hold_count: 1 } as never], isLoading: false, error: null },
      equipmentAttention: { data: undefined, isLoading: false, error: new Error("boom") },
    });
    const segments = segmentForAttention(sources);
    const equipmentSegment = segments.find((s) => s.key === "attention-equipment")!;
    const qualityHoldSegment = segments.find((s) => s.key === "attention-quality-holds")!;

    expect(equipmentSegment.error).toBeInstanceOf(Error);
    expect(equipmentSegment.rows).toEqual([]);
    // The failed segment's rows are empty because nothing loaded, NOT
    // because the source is genuinely empty -- callers must check `.error`
    // before treating `.rows.length === 0` as a true empty state.
    expect(qualityHoldSegment.error).toBeNull();
    expect(qualityHoldSegment.rows).toHaveLength(1);
  });

  it("never fabricates a fact for a source that has not loaded yet", () => {
    const sources = baseSources({ waterAttention: { data: undefined, isLoading: true, error: null } });
    const segments = segmentForAttention(sources);
    const waterSegment = segments.find((s) => s.key === "attention-water")!;
    expect(waterSegment.isLoading).toBe(true);
    expect(waterSegment.rows).toEqual([]);
  });
});

describe("segmentsTotalCount", () => {
  it("sums rows across segments once every segment has settled", () => {
    const sources = baseSources({
      activeBatches: { data: [{ id: "b1", code: "B-001", open_quality_hold_count: 1 } as never], isLoading: false, error: null },
    });
    const segments = segmentForAttention(sources);
    expect(segmentsTotalCount(segments)).toBe(1);
  });

  it("returns undefined (never 0) while any segment is still loading", () => {
    const sources = baseSources({ waterAttention: { data: undefined, isLoading: true, error: null } });
    const segments = segmentForAttention(sources);
    expect(segmentsTotalCount(segments)).toBeUndefined();
  });

  it("returns undefined (never a partial count) when any segment has errored", () => {
    const sources = baseSources({ equipmentAttention: { data: undefined, isLoading: false, error: new Error("boom") } });
    const segments = segmentForAttention(sources);
    expect(segmentsTotalCount(segments)).toBeUndefined();
  });
});
