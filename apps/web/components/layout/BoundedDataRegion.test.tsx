import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { BoundedDataRegion } from "./BoundedDataRegion";

describe("BoundedDataRegion", () => {
  it("exposes an accessible region label when given one, and none when omitted", () => {
    const { rerender } = render(
      <BoundedDataRegion label="Trays in this Sowing">
        <p>rows</p>
      </BoundedDataRegion>,
    );
    expect(screen.getByRole("region", { name: "Trays in this Sowing" })).toBeInTheDocument();

    rerender(
      <BoundedDataRegion>
        <p>rows</p>
      </BoundedDataRegion>,
    );
    expect(screen.queryByRole("region")).not.toBeInTheDocument();
  });

  it("keeps heading, rows, and footer in DOM order, with the footer always present outside the scrolling rows", () => {
    render(
      <BoundedDataRegion label="Trays" heading={<span>Tray</span>} footer={<span>3 trays · 600 seeds</span>}>
        <ul>
          <li>ST-0001</li>
          <li>ST-0002</li>
        </ul>
      </BoundedDataRegion>,
    );
    const region = screen.getByRole("region", { name: "Trays" });
    const children = Array.from(region.children).map((el) => el.textContent);
    // Heading first, then the scrollable rows container, then the footer --
    // the footer's own element must never be inside the scrolling box, so a
    // long list scrolling never hides the running total with it.
    expect(children[0]).toBe("Tray");
    expect(children[children.length - 1]).toBe("3 trays · 600 seeds");
    expect(screen.getByText("ST-0001")).toBeInTheDocument();
    expect(screen.getByText("3 trays · 600 seeds")).toBeInTheDocument();
  });
});
