import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

let currentPathname = "/farms/farm-1/store-inventory";

vi.mock("next/navigation", () => ({
  usePathname: () => currentPathname,
}));

import { StoreSubNav } from "./StoreSubNav";

function nav() {
  return screen.getByRole("navigation", { name: "Store & Inventory" });
}

describe("StoreSubNav (PILOT-UX-005 closure: replaces the removed Store sidebar)", () => {
  it("marks Operations active on the Store Operations route", () => {
    currentPathname = "/farms/farm-1/store-inventory";
    render(<StoreSubNav farmId="farm-1" />);
    expect(within(nav()).getByRole("link", { name: "Operations" })).toHaveAttribute("aria-current", "page");
    expect(within(nav()).getByRole("link", { name: "Inventory" })).not.toHaveAttribute("aria-current");
  });

  it("marks Inventory active on the Inventory route", () => {
    currentPathname = "/farms/farm-1/store-inventory/inventory";
    render(<StoreSubNav farmId="farm-1" />);
    expect(within(nav()).getByRole("link", { name: "Inventory" })).toHaveAttribute("aria-current", "page");
    expect(within(nav()).getByRole("link", { name: "Operations" })).not.toHaveAttribute("aria-current");
  });

  it("falls back to Operations active on a task route not in the subnav itself (e.g. Quality)", () => {
    currentPathname = "/farms/farm-1/store-inventory/quality";
    render(<StoreSubNav farmId="farm-1" />);
    expect(within(nav()).getByRole("link", { name: "Operations" })).toHaveAttribute("aria-current", "page");
  });

  it("hrefs point at the unchanged existing routes", () => {
    currentPathname = "/farms/farm-1/store-inventory";
    render(<StoreSubNav farmId="farm-1" />);
    expect(within(nav()).getByRole("link", { name: "Operations" })).toHaveAttribute(
      "href", "/farms/farm-1/store-inventory",
    );
    expect(within(nav()).getByRole("link", { name: "Inventory" })).toHaveAttribute(
      "href", "/farms/farm-1/store-inventory/inventory",
    );
  });
});
