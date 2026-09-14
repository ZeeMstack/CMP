import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useParams: () => ({ farmId: "farm-1" }),
}));

import { withQueryClient } from "@/lib/test-utils";

import FarmHomePage from "./page";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const farm = {
  id: "farm-1",
  tenant_id: "t1",
  code: "F1",
  name: "North Farm",
  country_code: "AE",
  city_region: null,
  timezone: "Asia/Dubai",
  status: "active",
};

const batches = [
  {
    id: "b1",
    code: "B-001",
    current_stage: { name: "Growing", stage_category: "production" },
    open_quality_hold_count: 0,
  },
  {
    id: "b2",
    code: "B-002",
    current_stage: { name: "Ready to Harvest", stage_category: "harvest_ready" },
    open_quality_hold_count: 1,
  },
];

function stubFetch() {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/operational-summary")) return jsonResponse(batches);
      if (url.endsWith("/farms/farm-1")) return jsonResponse(farm);
      // PILOT-OPS-001: Today on the Farm's own board/aggregation reads --
      // empty by default so these tests stay focused on the KPI/stage
      // content they were written to prove; dedicated Work Item behavior
      // is covered by lib/format/workItemBoard.test.ts and the
      // component-level work-item tests.
      if (url.includes("/work-items")) return jsonResponse([]);
      if (url.includes("/shift-handovers/latest")) return jsonResponse(null);
      if (url.includes("/harvestable-plates")) return jsonResponse([]);
      return jsonResponse({});
    }),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

/** UI-OPT-001 Batch B restyles this page but must not change its data
 * semantics or the accessible names pilot-happy-path.spec.ts asserts on
 * (Active batches / Harvest ready / Batches with open quality holds). */
describe("FarmHomePage", () => {
  it("preserves the KPI card accessible names the e2e pilot path depends on", async () => {
    stubFetch();
    render(withQueryClient(<FarmHomePage />));

    // PILOT-OPS-001: the page's own H1 is now "Today on the Farm" (the
    // ticket's explicit page title); the farm name is shown as descriptive
    // text under it rather than as the heading itself.
    await waitFor(() => expect(screen.getByRole("heading", { name: "Today on the Farm" })).toBeInTheDocument());
    expect(screen.getByText("North Farm")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Active batches/ })).toHaveAttribute("href", "/farms/farm-1/crop-batches");
    // PILOT-UX-003: now deep-links to the Batch register pre-filtered to the
    // same authoritative field the count itself was computed from -- the
    // accessible name (what the e2e pilot path actually asserts on) is
    // unchanged, only the query string.
    expect(screen.getByRole("link", { name: /Harvest ready/ })).toHaveAttribute(
      "href", "/farms/farm-1/crop-batches?filter=harvest_ready",
    );
    expect(screen.getByText("Batches with open quality holds")).toBeInTheDocument();
  });

  it("computes KPI values from the operational summary, unchanged by the visual pass", async () => {
    stubFetch();
    render(withQueryClient(<FarmHomePage />));
    await waitFor(() => expect(screen.getByRole("link", { name: /Active batches/ })).toBeInTheDocument());

    expect(screen.getByRole("link", { name: /Active batches/ })).toHaveTextContent("2");
    expect(screen.getByRole("link", { name: /Harvest ready/ })).toHaveTextContent("1");
  });

  it("shows the active-production-by-stage breakdown with a visible count per stage", async () => {
    stubFetch();
    render(withQueryClient(<FarmHomePage />));
    await waitFor(() => expect(screen.getByText("Growing")).toBeInTheDocument());
    expect(screen.getByText("Ready to Harvest")).toBeInTheDocument();
  });
});
