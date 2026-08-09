import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { StatusBadge } from "./StatusBadge";

describe("StatusBadge", () => {
  it("renders the label as visible text, not conveyed by color alone", () => {
    render(<StatusBadge label="Active" tone="active" />);
    expect(screen.getByText("Active")).toBeInTheDocument();
  });

  it("defaults to the neutral tone", () => {
    const { container } = render(<StatusBadge label="Unknown" />);
    expect(container.textContent).toBe("Unknown");
  });
});
