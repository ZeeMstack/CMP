import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useParams: () => ({ farmId: "farm-1", greenhouseId: "gh-1" }),
}));

import { withQueryClient } from "@/lib/test-utils";

import GreenhouseStructurePage from "./page";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const structure = {
  greenhouse_id: "gh-1",
  code: "GH-L01",
  name: "Leafy GH",
  classification: "leafy_greens",
  leafy_zones: [
    {
      id: "z1",
      code: "Z01",
      spans: [{ id: "s1", code: "S01", tables: [{ id: "t1", code: "T01", capacity: 24 }] }],
    },
  ],
};

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("GreenhouseStructurePage", () => {
  it("renders the greenhouse structure and never shows an Edit action -- classification is immutable after creation", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(structure)));
    render(withQueryClient(<GreenhouseStructurePage />));

    await waitFor(() => expect(screen.getByText("Zone Z01")).toBeInTheDocument());
    expect(screen.queryByRole("link", { name: /edit/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /edit/i })).not.toBeInTheDocument();
  });

  it("links back to Locations & Occupancy for this farm", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(structure)));
    render(withQueryClient(<GreenhouseStructurePage />));
    await waitFor(() => expect(screen.getByText("Zone Z01")).toBeInTheDocument());
    expect(screen.getByRole("link", { name: /view locations & occupancy/i })).toHaveAttribute(
      "href",
      "/farms/farm-1/locations",
    );
  });
});
