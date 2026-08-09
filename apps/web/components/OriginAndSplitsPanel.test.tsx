import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { BatchLineageRead } from "@/lib/api/client";

import { OriginAndSplitsPanel } from "./OriginAndSplitsPanel";

type LineageEvent = BatchLineageRead["parents"][number];

function makeEvent(overrides: Partial<LineageEvent> = {}): LineageEvent {
  return {
    derivation_event_id: "event-1",
    derivation_kind: "split",
    effective_time: "2026-07-28T00:00:00Z",
    batch: { id: "b1", code: "LOT-007A" },
    recorded_plant_quantity_total: 999,
    recorded_carrier_assignment_count: 1,
    ...overrides,
  } as LineageEvent;
}

describe("OriginAndSplitsPanel", () => {
  it("shows an honest empty state for a plain batch with no lineage", () => {
    render(<OriginAndSplitsPanel lineage={{ batch_id: "b1", parents: [], children: [] }} farmId="f1" />);
    expect(screen.getByText("No recorded origin or split relationships")).toBeInTheDocument();
  });

  it("tells the split-child narrative: created from X via split", () => {
    render(
      <OriginAndSplitsPanel
        lineage={{
          batch_id: "b1",
          parents: [makeEvent({ derivation_kind: "split", batch: { id: "parent-1", code: "LOT-007" } })],
          children: [],
        }}
        farmId="f1"
      />,
    );
    expect(screen.getByText(/Created from/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "LOT-007" })).toBeInTheDocument();
    expect(screen.getByText(/via split\./)).toBeInTheDocument();
  });

  it("tells the split-parent narrative: this batch was split into its children", () => {
    render(
      <OriginAndSplitsPanel
        lineage={{
          batch_id: "b1",
          parents: [],
          children: [
            makeEvent({ derivation_event_id: "evt-1", batch: { id: "b2", code: "LOT-007A" } }),
            makeEvent({ derivation_event_id: "evt-1", batch: { id: "b3", code: "LOT-007B" } }),
          ],
        }}
        farmId="f1"
      />,
    );
    expect(screen.getByText("This batch was split into:")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "LOT-007A" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "LOT-007B" })).toBeInTheDocument();
  });

  it("shows both ancestry and descendants coherently when both exist", () => {
    render(
      <OriginAndSplitsPanel
        lineage={{
          batch_id: "b1",
          parents: [makeEvent({ derivation_kind: "split", batch: { id: "parent-1", code: "LOT-005" } })],
          children: [makeEvent({ derivation_event_id: "evt-2", batch: { id: "child-1", code: "LOT-005B-A" } })],
        }}
        farmId="f1"
      />,
    );
    expect(screen.getByRole("link", { name: "LOT-005" })).toBeInTheDocument();
    expect(screen.getByText("This batch was split into:")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "LOT-005B-A" })).toBeInTheDocument();
  });

  it("never shows plant quantity fields", () => {
    const { container } = render(
      <OriginAndSplitsPanel
        lineage={{
          batch_id: "b1",
          parents: [makeEvent({ recorded_plant_quantity_total: 12345 })],
          children: [],
        }}
        farmId="f1"
      />,
    );
    expect(container.textContent).not.toContain("12345");
  });
});
