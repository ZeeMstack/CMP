import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useParams: () => ({ farmId: "farm-1" }),
}));

import { withQueryClient } from "@/lib/test-utils";

import FarmSetupOverviewPage from "./page";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("FarmSetupOverviewPage", () => {
  it("shows an honest, non-technical empty state with a primary 'Add greenhouse' action when there are no greenhouses", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse([])));
    render(withQueryClient(<FarmSetupOverviewPage />));

    await waitFor(() => expect(screen.getByText("No greenhouses configured yet.")).toBeInTheDocument());
    const addLinks = screen.getAllByRole("link", { name: /add greenhouse/i });
    expect(addLinks.length).toBeGreaterThan(0);
    expect(addLinks[0]).toHaveAttribute("href", "/farms/farm-1/farm-setup/new");
    // No technical instructions/jargon in the empty state.
    expect(screen.queryByText(/location_type_id|UUID|hierarchy_rule/i)).not.toBeInTheDocument();
  });

  it("renders one card per configured greenhouse from real data, never fabricated", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        jsonResponse([
          {
            greenhouse_id: "gh-1", code: "GH-01", name: "Greenhouse 1", classification: "leafy_greens", status: "configured",
            counts: {
              zones: 2, spans: 4, tables: 12, gutters: 0, bag_positions: 0,
              seedling_tables: 0, intersalads_tables: 0, intervines_tables: 0,
              trolleys: 0, trolley_levels: 0, trolley_slots: 0, seeding_machines: 0,
            },
          },
        ]),
      ),
    );
    render(withQueryClient(<FarmSetupOverviewPage />));

    await waitFor(() => expect(screen.getByText("GH-01")).toBeInTheDocument());
    expect(screen.getByText("2 Zones · 4 Spans · 12 Tables")).toBeInTheDocument();
  });
});
