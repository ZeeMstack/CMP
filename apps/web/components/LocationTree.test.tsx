import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { LocationTreeNode, SubtreeOccupancyRead } from "@/lib/api/client";
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
            id: "table-1-pos-1",
            code: "T1-P1",
            name: "Position 1",
            location_type_id: "type-position",
            status: "active",
            occupiable: true,
            children: [],
          },
          {
            id: "table-1-pos-2",
            code: "T1-P2",
            name: "Position 2",
            location_type_id: "type-position",
            status: "active",
            occupiable: true,
            children: [],
          },
        ],
      },
    ],
  },
];

function stubFetchWithSubtreeOccupancy(response: SubtreeOccupancyRead) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response(JSON.stringify(response), { status: 200, headers: { "Content-Type": "application/json" } })),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("LocationTree", () => {
  it("renders arbitrary nested depth without assuming a fixed hierarchy", () => {
    stubFetchWithSubtreeOccupancy({ root_location_id: "gh-1", aggregate_counts: [], occupied_locations: [] });
    render(withQueryClient(<LocationTree nodes={tree} farmId="farm-1" />));

    // Root auto-expands, revealing its immediate child.
    expect(screen.getByText("Greenhouse 1")).toBeInTheDocument();
    expect(screen.getByText("Zone A")).toBeInTheDocument();
    // The grandchild is not shown until Zone A is expanded.
    expect(screen.queryByText("Position 1")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /expand zone a/i }));
    expect(screen.getByText("Position 1")).toBeInTheDocument();
  });

  it("never shows a per-leaf 'Check occupancy' interaction", () => {
    stubFetchWithSubtreeOccupancy({ root_location_id: "gh-1", aggregate_counts: [], occupied_locations: [] });
    render(withQueryClient(<LocationTree nodes={tree} farmId="farm-1" />));
    fireEvent.click(screen.getByRole("button", { name: /expand zone a/i }));
    expect(screen.queryByRole("button", { name: /check occupancy/i })).not.toBeInTheDocument();
    expect(screen.queryByText(/check occupancy/i)).not.toBeInTheDocument();
  });

  it("renders aggregate occupancy counts at structural nodes once the branch's subtree data loads", async () => {
    stubFetchWithSubtreeOccupancy({
      root_location_id: "gh-1",
      aggregate_counts: [
        { location_id: "gh-1", occupiable_location_count: 2, occupied_location_count: 1 },
        { location_id: "zone-a", occupiable_location_count: 2, occupied_location_count: 1 },
      ],
      occupied_locations: [],
    });
    render(withQueryClient(<LocationTree nodes={tree} farmId="farm-1" />));

    await waitFor(() => expect(screen.getAllByText("1 / 2 occupied").length).toBeGreaterThan(0));
  });

  it("shows occupied-location detail (batch/crop/stage prominent, carrier secondary) without any click", async () => {
    stubFetchWithSubtreeOccupancy({
      root_location_id: "gh-1",
      aggregate_counts: [{ location_id: "gh-1", occupiable_location_count: 2, occupied_location_count: 1 }],
      occupied_locations: [
        {
          location_id: "table-1-pos-1",
          occupant: {
            kind: "carrier",
            id: "carrier-1",
            carrier_code: "PLATE-01",
            batch: {
              batch_id: "batch-1",
              batch_code: "LOT-006",
              crop: { id: "crop-1", code: "LETTUCE", common_name: "Lettuce" },
              current_stage: { id: "stage-1", code: "GROW", name: "Growing", is_terminal: false, stage_category: "production" },
            },
          },
        },
      ],
    });
    render(withQueryClient(<LocationTree nodes={tree} farmId="farm-1" />));
    fireEvent.click(screen.getByRole("button", { name: /expand zone a/i }));

    await waitFor(() => expect(screen.getByText("LOT-006")).toBeInTheDocument());
    expect(screen.getByText(/Lettuce/)).toBeInTheDocument();
    expect(screen.getByText("PLATE-01")).toBeInTheDocument();
  });

  it("shows an implicit Empty state for an occupiable location absent from occupied_locations, with no click needed", async () => {
    stubFetchWithSubtreeOccupancy({
      root_location_id: "gh-1",
      aggregate_counts: [{ location_id: "gh-1", occupiable_location_count: 2, occupied_location_count: 0 }],
      occupied_locations: [],
    });
    render(withQueryClient(<LocationTree nodes={tree} farmId="farm-1" />));
    fireEvent.click(screen.getByRole("button", { name: /expand zone a/i }));

    await waitFor(() => expect(screen.getAllByText("Empty").length).toBe(2));
  });
});
