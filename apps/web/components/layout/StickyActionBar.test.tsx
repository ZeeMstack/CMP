import { act, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { STICKY_ACTION_BAR_FALLBACK_HEIGHT_PX, StickyActionBar } from "./StickyActionBar";

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

  describe("UX-OPS-001C/R2: single measured mobile clearance", () => {
    afterEach(() => {
      vi.unstubAllGlobals();
    });

    it("reserves the fallback height (mobile-only placeholder, not an action) where ResizeObserver is unavailable", () => {
      vi.stubGlobal("ResizeObserver", undefined);
      render(
        <StickyActionBar>
          <button type="button">Review</button>
        </StickyActionBar>,
      );
      const spacer = screen.getByTestId("sticky-action-bar-spacer");
      expect(spacer).toHaveStyle({ height: `${STICKY_ACTION_BAR_FALLBACK_HEIGHT_PX}px` });
      expect(spacer).toHaveClass("lg:hidden");
      expect(spacer).toHaveAttribute("aria-hidden", "true");
      expect(spacer.querySelector("button")).toBeNull();
      expect(screen.getAllByRole("button", { name: "Review" })).toHaveLength(1);
    });

    it("tracks the bar's measured height as its content (e.g. an error) grows", () => {
      let notify: () => void = () => undefined;
      class FakeResizeObserver {
        constructor(callback: () => void) {
          notify = callback;
        }
        observe() {}
        disconnect() {}
      }
      vi.stubGlobal("ResizeObserver", FakeResizeObserver);
      const rect = vi.spyOn(HTMLElement.prototype, "getBoundingClientRect");
      render(
        <StickyActionBar blockers={<p role="alert">Unconfirmed — Retry sends the same request.</p>}>
          <button type="button">Retry</button>
        </StickyActionBar>,
      );
      rect.mockReturnValue({ height: 188 } as DOMRect);
      act(() => notify());
      expect(screen.getByTestId("sticky-action-bar-spacer")).toHaveStyle({ height: "188px" });
      // A zero/transient measurement never collapses the reservation.
      rect.mockReturnValue({ height: 0 } as DOMRect);
      act(() => notify());
      expect(screen.getByTestId("sticky-action-bar-spacer")).toHaveStyle({ height: "188px" });
      rect.mockRestore();
    });
  });
});
