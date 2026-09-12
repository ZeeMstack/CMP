import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { withQueryClient } from "@/lib/test-utils";

let searchParams = new URLSearchParams();
const pushMock = vi.fn();

vi.mock("next/navigation", () => ({
  useParams: () => ({ farmId: "farm-1" }),
  useSearchParams: () => searchParams,
  useRouter: () => ({ push: pushMock }),
}));

import CropBatchesPage from "./page";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const BATCH_GROWING = {
  id: "b1", code: "B-001", crop: { id: "crop-1", code: "LET", common_name: "Lettuce" }, variety: null,
  state: "active",
  current_stage: { id: "s1", code: "GROW", name: "Growing", is_terminal: false, stage_category: "production" },
  sowing_origins: [], sown_effective_time: null,
  placement: { active_carrier_count: 0, placed_carrier_count: 0, unplaced_carrier_count: 0, placements: [], common_ancestor_path: null },
  open_quality_hold_count: 0,
};
const BATCH_HARVEST_READY = {
  ...BATCH_GROWING, id: "b2", code: "B-002",
  current_stage: { id: "s2", code: "READY", name: "Ready to Harvest", is_terminal: false, stage_category: "harvest_ready" },
};
const BATCH_ON_HOLD = {
  ...BATCH_GROWING, id: "b3", code: "B-003", open_quality_hold_count: 1,
};

function stubFetch() {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/operational-summary")) {
        return jsonResponse([BATCH_GROWING, BATCH_HARVEST_READY, BATCH_ON_HOLD]);
      }
      if (url.endsWith("/farms/farm-1")) {
        return jsonResponse({ id: "farm-1", tenant_id: "t1", code: "F1", name: "North Farm", country_code: "AE", city_region: null, timezone: "Asia/Dubai", status: "active" });
      }
      return jsonResponse({});
    }),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
  searchParams = new URLSearchParams();
  pushMock.mockClear();
});

// `ResponsiveBatchList` renders both its mobile-card and desktop-table
// layouts simultaneously (toggled with responsive CSS, not conditional
// rendering), so every batch code legitimately appears twice.
function batchCount(code: string) {
  return screen.queryAllByText(code).length;
}

describe("CropBatchesPage", () => {
  it("shows every batch when no deep-link filter is present", async () => {
    stubFetch();
    render(withQueryClient(<CropBatchesPage />));
    await waitFor(() => expect(batchCount("B-001")).toBeGreaterThan(0));
    expect(batchCount("B-002")).toBeGreaterThan(0);
    expect(batchCount("B-003")).toBeGreaterThan(0);
    expect(screen.queryByText(/^Showing:/)).not.toBeInTheDocument();
  });

  it("PILOT-UX-003: ?filter=harvest_ready shows only stage_category=harvest_ready batches, with a visible filter banner", async () => {
    searchParams = new URLSearchParams("filter=harvest_ready");
    stubFetch();
    render(withQueryClient(<CropBatchesPage />));
    await waitFor(() => expect(batchCount("B-002")).toBeGreaterThan(0));
    expect(batchCount("B-001")).toBe(0);
    expect(batchCount("B-003")).toBe(0);
    expect(screen.getByText("Harvest ready")).toBeInTheDocument();
  });

  it("PILOT-UX-003: ?filter=quality_hold shows only batches with an open quality hold", async () => {
    searchParams = new URLSearchParams("filter=quality_hold");
    stubFetch();
    render(withQueryClient(<CropBatchesPage />));
    await waitFor(() => expect(batchCount("B-003")).toBeGreaterThan(0));
    expect(batchCount("B-001")).toBe(0);
    expect(batchCount("B-002")).toBe(0);
  });

  it("PILOT-UX-003: Clear filter navigates back to the unfiltered register", async () => {
    searchParams = new URLSearchParams("filter=harvest_ready");
    stubFetch();
    render(withQueryClient(<CropBatchesPage />));
    await waitFor(() => expect(batchCount("B-002")).toBeGreaterThan(0));
    fireEvent.click(screen.getByRole("button", { name: /clear filter/i }));
    expect(pushMock).toHaveBeenCalledWith("/farms/farm-1/crop-batches");
  });

  it("ignores an unrecognized filter value rather than silently showing an empty list", async () => {
    searchParams = new URLSearchParams("filter=bogus");
    stubFetch();
    render(withQueryClient(<CropBatchesPage />));
    await waitFor(() => expect(batchCount("B-001")).toBeGreaterThan(0));
    expect(batchCount("B-002")).toBeGreaterThan(0);
    expect(batchCount("B-003")).toBeGreaterThan(0);
  });
});
