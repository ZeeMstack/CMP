import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { Tabs } from "./Tabs";

const TABS = [
  { id: "overview", label: "Overview" },
  { id: "history", label: "History" },
];

describe("Tabs", () => {
  it("marks the active tab as selected and others as not selected", () => {
    render(<Tabs tabs={TABS} activeId="overview" onChange={vi.fn()} aria-label="Example sections" />);
    expect(screen.getByRole("tab", { name: "Overview" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tab", { name: "History" })).toHaveAttribute("aria-selected", "false");
  });

  it("is a plain controlled component -- clicking a tab does not change selection on its own", () => {
    render(<Tabs tabs={TABS} activeId="overview" onChange={vi.fn()} aria-label="Example sections" />);
    fireEvent.click(screen.getByRole("tab", { name: "History" }));
    // Still "overview" active because the caller hasn't fed back a new activeId.
    expect(screen.getByRole("tab", { name: "Overview" })).toHaveAttribute("aria-selected", "true");
  });

  it("calls onChange with the clicked tab's id", () => {
    const onChange = vi.fn();
    render(<Tabs tabs={TABS} activeId="overview" onChange={onChange} aria-label="Example sections" />);
    fireEvent.click(screen.getByRole("tab", { name: "History" }));
    expect(onChange).toHaveBeenCalledWith("history");
  });

  it("exposes an accessible tablist with the given label", () => {
    render(<Tabs tabs={TABS} activeId="overview" onChange={vi.fn()} aria-label="Example sections" />);
    expect(screen.getByRole("tablist", { name: "Example sections" })).toBeInTheDocument();
  });
});
