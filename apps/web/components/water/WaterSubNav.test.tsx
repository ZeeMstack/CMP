import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

let currentPathname = "/farms/farm-1/water";

vi.mock("next/navigation", () => ({
  usePathname: () => currentPathname,
}));

import { WaterSubNav } from "./WaterSubNav";

function nav() {
  return screen.getByRole("navigation", { name: "Water & Nutrients" });
}

describe("WaterSubNav (PILOT-WATER-001B navigation)", () => {
  it("renders exactly the six required tabs, in order", () => {
    render(<WaterSubNav farmId="farm-1" />);
    const links = within(nav()).getAllByRole("link");
    expect(links.map((l) => l.textContent)).toEqual([
      "Overview", "Measurements", "Mixing", "Delivery", "Exposure", "System Setup",
    ]);
  });

  it("marks Overview active on the workspace root route", () => {
    currentPathname = "/farms/farm-1/water";
    render(<WaterSubNav farmId="farm-1" />);
    expect(within(nav()).getByRole("link", { name: "Overview" })).toHaveAttribute("aria-current", "page");
    expect(within(nav()).getByRole("link", { name: "Measurements" })).not.toHaveAttribute("aria-current");
  });

  it("marks Measurements active on the measurements route", () => {
    currentPathname = "/farms/farm-1/water/measurements";
    render(<WaterSubNav farmId="farm-1" />);
    expect(within(nav()).getByRole("link", { name: "Measurements" })).toHaveAttribute("aria-current", "page");
  });

  it("marks System Setup active on the setup route, never confused with Overview by prefix", () => {
    currentPathname = "/farms/farm-1/water/setup";
    render(<WaterSubNav farmId="farm-1" />);
    expect(within(nav()).getByRole("link", { name: "System Setup" })).toHaveAttribute("aria-current", "page");
    expect(within(nav()).getByRole("link", { name: "Overview" })).not.toHaveAttribute("aria-current");
  });

  it("hrefs are all scoped under this Farm's water workspace", () => {
    currentPathname = "/farms/farm-1/water";
    render(<WaterSubNav farmId="farm-1" />);
    expect(within(nav()).getByRole("link", { name: "Mixing" })).toHaveAttribute("href", "/farms/farm-1/water/mixing");
    expect(within(nav()).getByRole("link", { name: "Delivery" })).toHaveAttribute("href", "/farms/farm-1/water/delivery");
    expect(within(nav()).getByRole("link", { name: "Exposure" })).toHaveAttribute("href", "/farms/farm-1/water/exposure");
  });
});

describe("WaterSubNav unresolved-command lock (UX-OPS-001D)", () => {
  it("keeps the active view but makes every other view non-navigable while locked, and says why", () => {
    currentPathname = "/farms/farm-1/water/delivery";
    render(<WaterSubNav farmId="farm-1" locked />);
    const links = within(nav()).getAllByRole("link");
    expect(links.map((l) => l.textContent)).toEqual(["Delivery"]);
    expect(within(nav()).getByText("Mixing")).toHaveAttribute("aria-disabled", "true");
    expect(within(nav()).getByRole("status")).toHaveTextContent(/retry the current command/i);
  });
});
