import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { QualityHoldBanner } from "./QualityHoldBanner";

describe("QualityHoldBanner", () => {
  it("renders nothing when there is no open hold", () => {
    const { container } = render(<QualityHoldBanner count={0} href="/quality" />);
    expect(container).toBeEmptyDOMElement();
  });

  it("uses singular copy for exactly one open hold", () => {
    render(<QualityHoldBanner count={1} href="/quality" />);
    expect(screen.getByText("This batch currently has 1 open quality hold.")).toBeInTheDocument();
  });

  it("uses plural copy for multiple open holds", () => {
    render(<QualityHoldBanner count={2} href="/quality" />);
    expect(screen.getByText("This batch currently has 2 open quality holds.")).toBeInTheDocument();
  });

  it("links to the quality tab", () => {
    render(<QualityHoldBanner count={1} href="/farms/f1/crop-batches/b1?tab=quality" />);
    const link = screen.getByRole("link", { name: "View quality details" });
    expect(link.getAttribute("href")).toBe("/farms/f1/crop-batches/b1?tab=quality");
  });
});
