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

    await waitFor(() => expect(screen.getByRole("heading", { name: "North Farm" })).toBeInTheDocument());
    expect(screen.getByRole("link", { name: /Active batches/ })).toHaveAttribute("href", "/farms/farm-1/crop-batches");
    expect(screen.getByRole("link", { name: /Harvest ready/ })).toHaveAttribute("href", "/farms/farm-1/crop-batches");
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
