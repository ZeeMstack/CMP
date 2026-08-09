import { describe, expect, it } from "vitest";

import type { LocationPathSegment, PlacementFacts } from "@/lib/api/client";

import { formatPlacementSummary } from "./placement";

function seg(id: string, name: string): LocationPathSegment {
  return { id, code: id.toUpperCase(), name };
}

const GH1 = seg("gh1", "Greenhouse 01");
const ZA = seg("za", "Zone A");
const SPAN = seg("span1", "Span 1");
const TABLE = seg("gt1", "Grow Table 1");
const P1 = seg("p1", "Position 01");
const P2 = seg("p2", "Position 02");

const GH2 = seg("gh2", "Greenhouse 02");
const ZB = seg("zb", "Zone B");
const OTHER_P = seg("op1", "Position 01");

function facts(overrides: Partial<PlacementFacts>): PlacementFacts {
  return {
    active_carrier_count: 0,
    placed_carrier_count: 0,
    unplaced_carrier_count: 0,
    placements: [],
    common_ancestor_path: null,
    ...overrides,
  };
}

describe("formatPlacementSummary", () => {
  it("A: reports zero active carriers truthfully", () => {
    expect(formatPlacementSummary(facts({ active_carrier_count: 0 }))).toBe("No current carriers");
  });

  it("B: reports an active-but-unplaced carrier as not yet placed", () => {
    expect(
      formatPlacementSummary(facts({ active_carrier_count: 1, placed_carrier_count: 0, unplaced_carrier_count: 1 })),
    ).toBe("Not yet placed");
  });

  it("C: renders a concise two-level path for exactly one occupied location", () => {
    const result = formatPlacementSummary(
      facts({
        active_carrier_count: 1,
        placed_carrier_count: 1,
        placements: [
          {
            carrier_id: "c1",
            carrier_code: "PLATE-1",
            location_id: "p1",
            location_code: "P01",
            location_name: "Position 01",
            path: [GH1, ZA, SPAN, TABLE, P1],
          },
        ],
        common_ancestor_path: [GH1, ZA, SPAN, TABLE, P1],
      }),
    );
    expect(result).toBe("Greenhouse 01 / Zone A");
    // Must never dump the full technical leaf path/code.
    expect(result).not.toContain("Grow Table");
    expect(result).not.toContain("P01");
  });

  it("D: renders a shared common ancestor with a location count for multiple placements", () => {
    const result = formatPlacementSummary(
      facts({
        active_carrier_count: 2,
        placed_carrier_count: 2,
        placements: [
          { carrier_id: "c1", carrier_code: "P1", location_id: "p1", location_code: "P01", location_name: "Position 01", path: [GH2, ZA, SPAN, TABLE, P1] },
          { carrier_id: "c2", carrier_code: "P2", location_id: "p2", location_code: "P02", location_name: "Position 02", path: [GH2, ZA, SPAN, TABLE, P2] },
        ],
        common_ancestor_path: [GH2, ZA, SPAN, TABLE],
      }),
    );
    expect(result).toBe("Greenhouse 02 / Zone A · 2 locations");
  });

  it("E: never hides unplaced active carriers alongside a shared-ancestor placement", () => {
    const result = formatPlacementSummary(
      facts({
        active_carrier_count: 3,
        placed_carrier_count: 2,
        unplaced_carrier_count: 1,
        placements: [
          { carrier_id: "c1", carrier_code: "P1", location_id: "p1", location_code: "P01", location_name: "Position 01", path: [GH1, ZA, SPAN, TABLE, P1] },
          { carrier_id: "c2", carrier_code: "P2", location_id: "p2", location_code: "P02", location_name: "Position 02", path: [GH1, ZA, SPAN, TABLE, P2] },
        ],
        common_ancestor_path: [GH1, ZA, SPAN, TABLE],
      }),
    );
    expect(result).toBe("Greenhouse 01 / Zone A · 2 locations · 1 unplaced");
  });

  it("F: reports a truthful branch count when placements share no common ancestor", () => {
    const result = formatPlacementSummary(
      facts({
        active_carrier_count: 3,
        placed_carrier_count: 3,
        placements: [
          { carrier_id: "c1", carrier_code: "P1", location_id: "p1", location_code: "P01", location_name: "Position 01", path: [GH1, ZA, P1] },
          { carrier_id: "c2", carrier_code: "P2", location_id: "op1", location_code: "P01", location_name: "Position 01", path: [GH2, ZB, OTHER_P] },
          { carrier_id: "c3", carrier_code: "P3", location_id: "p2", location_code: "P02", location_name: "Position 02", path: [GH1, ZA, P2] },
        ],
        common_ancestor_path: null,
      }),
    );
    expect(result).toBe("3 locations across 2 branches");
  });

  it("never arbitrarily reports a single 'current location' by picking the first placement out of several", () => {
    // Scattered case (F) must not degrade into treating placements[0] as "the" location.
    const result = formatPlacementSummary(
      facts({
        active_carrier_count: 2,
        placed_carrier_count: 2,
        placements: [
          { carrier_id: "c1", carrier_code: "P1", location_id: "p1", location_code: "P01", location_name: "Position 01", path: [GH1, ZA, P1] },
          { carrier_id: "c2", carrier_code: "P2", location_id: "op1", location_code: "P01", location_name: "Position 01", path: [GH2, ZB, OTHER_P] },
        ],
        common_ancestor_path: null,
      }),
    );
    expect(result).not.toContain("Greenhouse 01 / Zone A");
    expect(result).toContain("2 locations across 2 branches");
  });
});
