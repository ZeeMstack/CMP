import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useParams: () => ({ farmId: "farm-1" }),
}));

import { withQueryClient } from "@/lib/test-utils";

import LocationsPage from "./page";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const tree = [
  {
    id: "gh-1",
    code: "GH1",
    name: "Greenhouse 1",
    location_type_id: "type-gh",
    status: "active",
    occupiable: false,
    capacity: null,
    children: [],
  },
];

function stubFetch() {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/subtree-occupancy")) {
        return jsonResponse({ root_location_id: "gh-1", aggregate_counts: [], occupied_locations: [] });
      }
      if (url.includes("/locations/tree")) return jsonResponse(tree);
      return jsonResponse({});
    }),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("LocationsPage", () => {
  it("renders the location tree (this wrapper restyle must not break tree rendering/expansion)", async () => {
    stubFetch();
    render(withQueryClient(<LocationsPage />));
    await waitFor(() => expect(screen.getByText("Greenhouse 1")).toBeInTheDocument());
  });

  it("provides a way back to Farm Setup, distinct from this operational occupancy view", async () => {
    stubFetch();
    render(withQueryClient(<LocationsPage />));
    await waitFor(() => expect(screen.getByText("Greenhouse 1")).toBeInTheDocument());
    expect(screen.getByRole("link", { name: /view farm setup/i })).toHaveAttribute("href", "/farms/farm-1/farm-setup");
  });

  it("shows an honest empty state when there is no location hierarchy yet", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse([])));
    render(withQueryClient(<LocationsPage />));
    await waitFor(() => expect(screen.getByText("No locations yet")).toBeInTheDocument());
  });
});
