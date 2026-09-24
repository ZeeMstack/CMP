import { render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { withQueryClient } from "@/lib/test-utils";

vi.mock("next/navigation", async () =>
  (await import("@/components/water/waterTestNavigation")).createNavigationMock("/farms/farm-1/water"),
);

import WaterOverviewPage from "./page";

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const ONGOING = {
  id: "del-open", reservoir_id: "res-1", irrigation_circuit_id: "ic-1", effective_start: "2026-09-24T05:00:00Z",
  effective_end: null, delivered_volume: null,
};

function stubFetch(overrides: Record<string, () => Response>) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      for (const [fragment, respond] of Object.entries(overrides)) if (url.includes(fragment)) return respond();
      if (url.includes("/water/attention")) return json([]);
      if (url.includes("/water-delivery-events")) return json([ONGOING]);
      if (url.includes("/irrigation-circuits")) return json([{ id: "ic-1", code: "IC-1", name: "Drip", status: "active" }]);
      if (url.includes("/reservoirs")) return json([{ id: "res-1", code: "RES-1", name: "Tank A", status: "active" }, { id: "res-2", code: "RES-2", name: "Tank B", status: "active" }]);
      if (url.includes("/water-sources")) return json([{ id: "ws-1", code: "WS-1", name: "Bore", status: "active" }, { id: "ws-2", code: "WS-2", name: "RO", status: "active" }]);
      return json([]);
    }),
  );
}

afterEach(() => vi.unstubAllGlobals());

describe("Water hub (UX-OPS-001D)", () => {
  it("puts the four task links first and ongoing deliveries with an End Delivery next action", async () => {
    stubFetch({});
    render(withQueryClient(<WaterOverviewPage />));
    const actions = within(screen.getByRole("navigation", { name: "Water actions" }));
    expect(actions.getAllByRole("link").map((l) => l.textContent)).toEqual([
      "Record measurements", "Record a mix", "Delivery", "Review exposure",
    ]);
    const ongoing = within(await screen.findByRole("region", { name: "Ongoing deliveries" }));
    expect(await ongoing.findByText("RES-1 — Tank A → IC-1 — Drip")).toBeInTheDocument();
    expect(ongoing.getByRole("link", { name: "End Delivery" })).toHaveAttribute(
      "href", "/farms/farm-1/water/delivery?selected=del-open&panel=end",
    );
    // Topology is supporting context, last, and never a singular source/tank.
    const topology = await screen.findByRole("region", { name: "Configured topology" });
    expect(topology).toHaveTextContent(/2 active of 2 — WS-1, WS-2/);
    expect(topology.compareDocumentPosition(screen.getByRole("region", { name: "Water Attention" })) & Node.DOCUMENT_POSITION_PRECEDING).toBeTruthy();
  });

  it("a failed Attention or activity read is shown as unavailable, never as 'nothing needs attention' or empty", async () => {
    stubFetch({
      "/water/attention": () => json({ detail: "down" }, 500),
      "/water-measurements": () => json({ detail: "down" }, 503),
    });
    render(withQueryClient(<WaterOverviewPage />));
    const attention = within(await screen.findByRole("region", { name: "Water Attention" }));
    expect(await attention.findByRole("alert")).toHaveTextContent("Water Attention unavailable");
    expect(screen.queryByText("Nothing currently needs Water attention.")).not.toBeInTheDocument();
    const measurements = within(screen.getByRole("region", { name: "Measurements" }));
    expect(await measurements.findByRole("alert")).toHaveTextContent("Measurements unavailable");
    expect(screen.queryByText("No measurements recorded yet.")).not.toBeInTheDocument();
    // Sibling sources are unaffected.
    expect(await screen.findByText("No mixes recorded yet.")).toBeInTheDocument();
  });
});
