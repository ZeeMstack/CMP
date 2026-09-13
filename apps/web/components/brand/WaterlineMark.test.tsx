import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { WaterlineWordmark } from "./WaterlineMark";

describe("WaterlineWordmark", () => {
  it("defaults to the light-background presentation (wl-canopy/wl-deepwater)", () => {
    render(<WaterlineWordmark />);
    expect(screen.getByText("grow")).toHaveClass("text-wl-canopy");
    expect(screen.getByText("CMP")).toHaveClass("text-wl-deepwater");
  });

  it("uses wl-text-on-brand for both words in the inverse variant, same mark and lockup", () => {
    const { container } = render(<WaterlineWordmark variant="inverse" />);
    expect(screen.getByText("grow")).toHaveClass("text-wl-text-on-brand");
    expect(screen.getByText("CMP")).toHaveClass("text-wl-text-on-brand");
    expect(container.querySelector("svg")).toBeInTheDocument();
  });
});
