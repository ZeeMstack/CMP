import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { AppError } from "@/lib/errors/adapter";
import type { HomeQueueRow, HomeQueueSegment } from "@/lib/format/homeQueue";

import { HomeQueueView } from "./HomeQueueView";

// HomeQueueView never reads `.data` (only id/sourceLabel/title/context/meta
// drive QueueRow's rendering) -- a minimal placeholder is fine here.
function okRow(overrides: Partial<HomeQueueRow> = {}): HomeQueueRow {
  return {
    id: "row-1", sourceLabel: "Equipment", title: "Trolley sensor fault",
    data: { kind: "equipment_attention", item: { kind: "OPEN_INCIDENT", message: "x" } } as unknown as HomeQueueRow["data"],
    ...overrides,
  };
}

function segment(overrides: Partial<HomeQueueSegment> = {}): HomeQueueSegment {
  return {
    key: "seg-1",
    sourceLabel: "Water",
    segmentLabel: "Water attention",
    isLoading: false,
    error: null,
    emptyLabel: "Nothing here.",
    rows: [],
    ...overrides,
  };
}

describe("HomeQueueView: R2 compact source-failure row", () => {
  it("shows a compact, queue-row-height failure row (role=alert) naming the source, not the large ErrorState card", () => {
    const failed = segment({
      key: "attention-water", segmentLabel: "Water attention",
      error: new AppError("server_error", "The server encountered an error."),
    });
    render(<HomeQueueView segments={[failed]} selectedId={null} onSelect={vi.fn()} onRetry={vi.fn()} />);

    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("Water attention");
    expect(alert).toHaveTextContent("unavailable");
    // The old global ErrorState card's own title/action copy must not
    // appear -- this is the compact row, never ErrorState.
    expect(screen.queryByText("Server error")).not.toBeInTheDocument();
    expect(screen.queryByText(/contact an administrator/i)).not.toBeInTheDocument();
  });

  it("the inline Retry action calls onRetry with that segment's own key", () => {
    const onRetry = vi.fn();
    const failed = segment({
      key: "attention-equipment", segmentLabel: "Equipment attention",
      error: new AppError("network_error", "Could not reach the backend."),
    });
    render(<HomeQueueView segments={[failed]} selectedId={null} onSelect={vi.fn()} onRetry={onRetry} />);

    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(onRetry).toHaveBeenCalledWith("attention-equipment");
  });

  it("a failed source does not hide or disable a successful sibling segment", () => {
    const failed = segment({
      key: "attention-water", segmentLabel: "Water attention",
      error: new AppError("server_error", "The server encountered an error."),
    });
    const ok = segment({
      key: "attention-equipment", segmentLabel: "Equipment attention", sourceLabel: "Equipment",
      rows: [okRow()],
    });
    render(<HomeQueueView segments={[failed, ok]} selectedId={null} onSelect={vi.fn()} onRetry={vi.fn()} />);

    expect(screen.getByRole("alert")).toBeInTheDocument();
    const row = screen.getByRole("button", { name: /Trolley sensor fault/ });
    expect(row).toBeInTheDocument();
    expect(row).toBeEnabled();
  });

  it("a failed segment leaves the still-loading sibling's own loading state intact", () => {
    const failed = segment({ key: "a", segmentLabel: "Attention A", error: new AppError("server_error", "Boom") });
    const loading = segment({ key: "b", segmentLabel: "Attention B", isLoading: true });
    render(<HomeQueueView segments={[failed, loading]} selectedId={null} onSelect={vi.fn()} onRetry={vi.fn()} />);

    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(screen.getByText(/Loading attention b/i)).toBeInTheDocument();
  });
});
