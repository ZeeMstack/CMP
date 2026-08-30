import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn() }),
}));

import { withQueryClient } from "@/lib/test-utils";

import FarmsPage from "./page";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const farmOne = {
  id: "farm-1",
  tenant_id: "t1",
  code: "F1",
  name: "North Farm",
  country_code: "AE",
  city_region: null,
  timezone: "Asia/Dubai",
  status: "active",
};
const farmTwo = {
  id: "farm-2",
  tenant_id: "t1",
  code: "F2",
  name: "South Farm",
  country_code: "AE",
  city_region: null,
  timezone: "Asia/Dubai",
  status: "active",
};

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("FarmsPage", () => {
  it("offers a Create Farm action routing to /farms/new when the tenant has zero Farms", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse([])));
    render(withQueryClient(<FarmsPage />));

    await waitFor(() =>
      expect(screen.getByText("No farms have been set up for this tenant yet.")).toBeInTheDocument(),
    );
    expect(screen.getByRole("link", { name: /create farm/i })).toHaveAttribute("href", "/farms/new");
  });

  it("still renders the farm picker for a tenant with multiple Farms, alongside a Create Farm action", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse([farmOne, farmTwo])));
    render(withQueryClient(<FarmsPage />));

    await waitFor(() => expect(screen.getByText("North Farm")).toBeInTheDocument());
    expect(screen.getByText("South Farm")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /create farm/i })).toHaveAttribute("href", "/farms/new");
  });

  it("never renders a tenant ID input or selector on the Farms list itself", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse([])));
    render(withQueryClient(<FarmsPage />));

    await waitFor(() =>
      expect(screen.getByText("No farms have been set up for this tenant yet.")).toBeInTheDocument(),
    );
    expect(screen.queryByLabelText(/tenant/i)).not.toBeInTheDocument();
  });
});
