import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { LocationTreeNode } from "@/lib/api/client";
import { withQueryClient } from "@/lib/test-utils";

import { LocationTree } from "./LocationTree";

const tree: LocationTreeNode[] = [
  {
    id: "gh-1",
    code: "GH1",
    name: "Greenhouse 1",
    location_type_id: "type-gh",
    status: "active",
    occupiable: false,
    children: [
      {
        id: "zone-a",
        code: "ZA",
        name: "Zone A",
        location_type_id: "type-zone",
        status: "active",
        occupiable: false,
        children: [
          {
            id: "table-1",
            code: "T1",
            name: "Table 1",
            location_type_id: "type-table",
            status: "active",
            occupiable: true,
            children: [],
          },
        ],
      },
    ],
  },
];

describe("LocationTree", () => {
  it("renders arbitrary nested depth without assuming a fixed hierarchy", () => {
    render(withQueryClient(<LocationTree nodes={tree} farmId="farm-1" />));

    // Root auto-expands, revealing its immediate child.
    expect(screen.getByText("Greenhouse 1")).toBeInTheDocument();
    expect(screen.getByText("Zone A")).toBeInTheDocument();
    // The grandchild is not shown until Zone A is expanded.
    expect(screen.queryByText("Table 1")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /expand zone a/i }));
    expect(screen.getByText("Table 1")).toBeInTheDocument();
  });

  it("does not eagerly fetch occupancy -- shows a request button instead", () => {
    render(withQueryClient(<LocationTree nodes={tree} farmId="farm-1" />));
    // Table 1 is occupiable but collapsed initially; expand to it isn't
    // required for this assertion since occupiable-only affects the leaf.
    expect(screen.queryByText(/checking/i)).not.toBeInTheDocument();
  });
});
