import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { BatchOperationalContext } from "@/lib/api/client";

import { ResponsiveBatchList } from "./ResponsiveBatchList";

function makeBatch(overrides: Partial<BatchOperationalContext> = {}): BatchOperationalContext {
  return {
    id: "batch-1",
    code: "BATCH-001",
    crop: { id: "crop-1", code: "LETTUCE", common_name: "Lettuce" },
    variety: { id: "var-1", code: "ICE", name: "Iceberg" },
    state: "active",
    current_stage: { id: "stage-1", code: "GROW", name: "Growing", is_terminal: false, stage_category: "production" },
    sowing_origins: [],
    sown_effective_time: null,
    placement: {
      active_carrier_count: 0,
      placed_carrier_count: 0,
      unplaced_carrier_count: 0,
      placements: [],
      common_ancestor_path: null,
    },
    open_quality_hold_count: 0,
    ...overrides,
  };
}

describe("ResponsiveBatchList", () => {
  it("renders a link to each batch's detail page with its code", () => {
    const batches = [makeBatch({ id: "b1", code: "BATCH-001" }), makeBatch({ id: "b2", code: "BATCH-002" })];
    render(<ResponsiveBatchList batches={batches} farmId="farm-1" />);

    const links = screen.getAllByRole("link", { name: /BATCH-00/ });
    expect(links.length).toBeGreaterThanOrEqual(2);
    expect(links.some((l) => l.getAttribute("href") === "/farms/farm-1/crop-batches/b1")).toBe(true);
  });

  it("shows crop and variety for each batch", () => {
    render(<ResponsiveBatchList batches={[makeBatch()]} farmId="farm-1" />);
    expect(screen.getAllByText(/Lettuce/).length).toBeGreaterThan(0);
  });

  it("shows an unmistakable On hold badge for a batch with an open quality hold", () => {
    render(<ResponsiveBatchList batches={[makeBatch({ open_quality_hold_count: 1 })]} farmId="farm-1" />);
    expect(screen.getAllByText("On hold").length).toBeGreaterThan(0);
  });

  it("shows no On hold badge for a batch without an open quality hold", () => {
    render(<ResponsiveBatchList batches={[makeBatch({ open_quality_hold_count: 0 })]} farmId="farm-1" />);
    expect(screen.queryByText("On hold")).not.toBeInTheDocument();
  });

  it("renders placement information for each batch", () => {
    render(<ResponsiveBatchList batches={[makeBatch()]} farmId="farm-1" />);
    expect(screen.getAllByText("No current carriers").length).toBeGreaterThan(0);
  });

  it("makes superseded and closed states visually obvious via a badge", () => {
    render(
      <ResponsiveBatchList
        batches={[makeBatch({ id: "b1", state: "superseded" }), makeBatch({ id: "b2", state: "closed" })]}
        farmId="farm-1"
      />,
    );
    expect(screen.getAllByText("superseded").length).toBeGreaterThan(0);
    expect(screen.getAllByText("closed").length).toBeGreaterThan(0);
  });

  it("does not render an equally-weighted badge for the common active state", () => {
    render(<ResponsiveBatchList batches={[makeBatch({ state: "active" })]} farmId="farm-1" />);
    // "Active" appears as plain muted text, not inside a StatusBadge pill --
    // there should be no badge-styled element carrying that label.
    const activeLabels = screen.getAllByText("Active");
    for (const el of activeLabels) {
      expect(el.className).not.toContain("rounded-full");
    }
  });
});
