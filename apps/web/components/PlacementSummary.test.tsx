import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { PlacementFacts } from "@/lib/api/client";

import { PlacementSummary } from "./PlacementSummary";

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

describe("PlacementSummary", () => {
  it("renders the zero-carrier case", () => {
    render(<PlacementSummary placement={facts({ active_carrier_count: 0 })} />);
    expect(screen.getByText("No current carriers")).toBeInTheDocument();
  });

  it("renders the not-yet-placed case", () => {
    render(
      <PlacementSummary
        placement={facts({ active_carrier_count: 1, placed_carrier_count: 0, unplaced_carrier_count: 1 })}
      />,
    );
    expect(screen.getByText("Not yet placed")).toBeInTheDocument();
  });
});
