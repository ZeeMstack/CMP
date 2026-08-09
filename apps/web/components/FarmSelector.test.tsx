import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { FarmRead } from "@/lib/api/client";

import { FarmSelector } from "./FarmSelector";

vi.mock("next/navigation", () => ({
  usePathname: () => "/farms/farm-1/locations",
}));

const farms: FarmRead[] = [
  { id: "farm-1", tenant_id: "t1", code: "F1", name: "North Farm", country_code: "AE", city_region: null, timezone: "Asia/Dubai", status: "active" },
  { id: "farm-2", tenant_id: "t1", code: "F2", name: "South Farm", country_code: "AE", city_region: null, timezone: "Asia/Dubai", status: "active" },
];

describe("FarmSelector", () => {
  it("renders plain text (no dropdown) when there is only one farm", () => {
    render(<FarmSelector farms={[farms[0]]} currentFarmId="farm-1" />);
    expect(screen.getByText("North Farm")).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("renders a selectable dropdown when there are multiple farms", () => {
    render(<FarmSelector farms={farms} currentFarmId="farm-1" />);
    expect(screen.getByRole("button", { name: /north farm/i })).toBeInTheDocument();
  });

  it("preserves the current sub-page (Locations) when switching farms", () => {
    render(<FarmSelector farms={farms} currentFarmId="farm-1" />);
    fireEvent.click(screen.getByRole("button", { name: /north farm/i }));
    const otherFarmLink = screen.getByRole("option", { name: /south farm/i }).querySelector("a");
    expect(otherFarmLink).toHaveAttribute("href", "/farms/farm-2/locations");
  });
});
