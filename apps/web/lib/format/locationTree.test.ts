import { describe, expect, it } from "vitest";

import { flattenLocationTree } from "./locationTree";
import type { LocationTreeNode } from "@/lib/api/client";

function node(overrides: Partial<LocationTreeNode> & { id: string; code: string; name: string }): LocationTreeNode {
  return {
    location_type_id: "type-1",
    status: "active",
    occupiable: false,
    capacity: null,
    children: [],
    ...overrides,
  };
}

describe("flattenLocationTree", () => {
  it("returns an empty list for an empty tree", () => {
    expect(flattenLocationTree([])).toEqual([]);
  });

  it("orders parents before children, depth-first", () => {
    const tree = [
      node({
        id: "cold-store", code: "CS1", name: "Cold Store",
        children: [
          node({ id: "pos-1", code: "P01", name: "Position 1" }),
          node({ id: "pos-2", code: "P02", name: "Position 2" }),
        ],
      }),
      node({ id: "packing-hall", code: "PH1", name: "Packing Hall" }),
    ];

    const flat = flattenLocationTree(tree);
    expect(flat.map((f) => f.id)).toEqual(["cold-store", "pos-1", "pos-2", "packing-hall"]);
  });

  it("increases depth by one per level and indents the label accordingly", () => {
    const tree = [node({ id: "root", code: "R1", name: "Root", children: [node({ id: "child", code: "C1", name: "Child" })] })];
    const flat = flattenLocationTree(tree);
    expect(flat[0]).toEqual({ id: "root", label: "Root (R1)", depth: 0 });
    expect(flat[1]).toEqual({ id: "child", label: "  Child (C1)", depth: 1 });
  });
});
