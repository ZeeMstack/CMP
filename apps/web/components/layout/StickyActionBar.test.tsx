import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { StickyActionBar } from "./StickyActionBar";

describe("StickyActionBar", () => {
  it("renders exactly one action control -- never a desktop copy and a separate mobile copy", () => {
    render(
      <StickyActionBar>
        <button type="button">Review Sowing</button>
      </StickyActionBar>,
    );
    expect(screen.getAllByRole("button", { name: "Review Sowing" })).toHaveLength(1);
  });

  it("renders blockers before the action control, both inside the one action surface", () => {
    render(
      <StickyActionBar blockers={<p role="alert">Fix the highlighted fields before continuing.</p>}>
        <button type="button">Review Sowing</button>
      </StickyActionBar>,
    );
    const alert = screen.getByRole("alert");
    const button = screen.getByRole("button", { name: "Review Sowing" });
    // DOM order: the blocker precedes the action, so it reads immediately
    // above it whether this bar is in normal flow (desktop rail) or pinned
    // to the viewport bottom (mobile/tablet).
    expect(alert.compareDocumentPosition(button) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("omits the blockers slot entirely when there is nothing to show", () => {
    render(
      <StickyActionBar>
        <button type="button">Record Sowing</button>
      </StickyActionBar>,
    );
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
