import { describe, expect, it } from "vitest";

import { suggestAllocations } from "./suggestAllocation";

describe("suggestAllocations", () => {
  it("fills destinations in order, respecting each one's known capacity", () => {
    const result = suggestAllocations(
      [{ sourceId: "s1", available: 200 }],
      [
        { destinationId: "d1", capacity: 120, existingAllocations: [] },
        { destinationId: "d2", capacity: 100, existingAllocations: [] },
      ],
    );
    expect(result.byDestinationId.d1).toEqual([{ sourceId: "s1", quantity: 120 }]);
    expect(result.byDestinationId.d2).toEqual([{ sourceId: "s1", quantity: 80 }]);
    expect(result.filledDestinationIds).toEqual(["d1", "d2"]);
  });

  it("spreads a destination's fill across multiple sources in order once one source is exhausted", () => {
    const result = suggestAllocations(
      [
        { sourceId: "s1", available: 50 },
        { sourceId: "s2", available: 80 },
      ],
      [{ destinationId: "d1", capacity: 100, existingAllocations: [] }],
    );
    expect(result.byDestinationId.d1).toEqual([
      { sourceId: "s1", quantity: 50 },
      { sourceId: "s2", quantity: 50 },
    ]);
  });

  it("never fills a destination with unknown capacity", () => {
    const result = suggestAllocations(
      [{ sourceId: "s1", available: 200 }],
      [{ destinationId: "d1", capacity: null, existingAllocations: [] }],
    );
    expect(result.byDestinationId.d1).toEqual([]);
    expect(result.filledDestinationIds).toEqual([]);
  });

  it("leaves a destination with an existing allocation untouched (operator override persists)", () => {
    const result = suggestAllocations(
      [{ sourceId: "s1", available: 200 }],
      [
        { destinationId: "d1", capacity: 100, existingAllocations: [{ sourceId: "s1", quantity: 10 }] },
        { destinationId: "d2", capacity: 100, existingAllocations: [] },
      ],
    );
    expect(result.byDestinationId.d1).toEqual([{ sourceId: "s1", quantity: 10 }]);
    // Locked d1 already consumed 10 from s1's budget of 200, leaving 190 for d2.
    expect(result.byDestinationId.d2).toEqual([{ sourceId: "s1", quantity: 100 }]);
    expect(result.filledDestinationIds).toEqual(["d2"]);
  });

  it("never proposes more than a source's remaining budget after locked destinations are subtracted", () => {
    const result = suggestAllocations(
      [{ sourceId: "s1", available: 50 }],
      [
        { destinationId: "d1", capacity: null, existingAllocations: [{ sourceId: "s1", quantity: 40 }] },
        { destinationId: "d2", capacity: 100, existingAllocations: [] },
      ],
    );
    expect(result.byDestinationId.d2).toEqual([{ sourceId: "s1", quantity: 10 }]);
  });

  it("produces no rows for a destination once every source is exhausted", () => {
    const result = suggestAllocations(
      [{ sourceId: "s1", available: 50 }],
      [
        { destinationId: "d1", capacity: 50, existingAllocations: [] },
        { destinationId: "d2", capacity: 50, existingAllocations: [] },
      ],
    );
    expect(result.byDestinationId.d1).toEqual([{ sourceId: "s1", quantity: 50 }]);
    expect(result.byDestinationId.d2).toEqual([]);
    expect(result.filledDestinationIds).toEqual(["d1", "d2"]);
  });
});
