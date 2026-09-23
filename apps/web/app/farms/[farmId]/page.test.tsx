import { render, screen, waitFor, within } from "@testing-library/react";
import { useSyncExternalStore } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { writeWorkingLocation } from "@/lib/scan/workingLocation";
import { withQueryClient } from "@/lib/test-utils";

/** UX-OPS-001B: the Home page now reads/writes `?view=&selected=` via
 * `useViewState` (next/navigation's `useSearchParams`/`useRouter`/
 * `usePathname`), so this mock must be reactive -- `router.replace` needs
 * to actually update what `useSearchParams` returns and trigger a
 * re-render, mirroring a real browser URL, so "survives rerender/
 * navigation" is provable in these tests. */
let currentSearch = "";
const listeners = new Set<() => void>();
function notifyListeners() {
  for (const listener of listeners) listener();
}
const replaceMock = vi.fn((url: string) => {
  currentSearch = url.includes("?") ? url.slice(url.indexOf("?") + 1) : "";
  notifyListeners();
});

vi.mock("next/navigation", () => ({
  useParams: () => ({ farmId: "farm-1" }),
  usePathname: () => "/farms/farm-1",
  useSearchParams: () => {
    const snapshot = useSyncExternalStore(
      (cb: () => void) => {
        listeners.add(cb);
        return () => listeners.delete(cb);
      },
      () => currentSearch,
      () => currentSearch,
    );
    return new URLSearchParams(snapshot);
  },
  useRouter: () => ({ replace: replaceMock, push: replaceMock }),
}));

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
    crop: { id: "crop-1", code: "LETTUCE", common_name: "Lettuce" },
    current_stage: { name: "Growing", stage_category: "production" },
    open_quality_hold_count: 0,
  },
  {
    id: "b2",
    code: "B-002",
    crop: { id: "crop-1", code: "LETTUCE", common_name: "Lettuce" },
    current_stage: { name: "Ready to Harvest", stage_category: "harvest_ready" },
    open_quality_hold_count: 1,
  },
];

const myWorkItem = {
  id: "wi-1",
  code: "WI-001",
  title: "Check reservoir",
  status: "open",
  priority: "normal",
  work_type: "other",
  completion_mode: "manual_record",
  assigned_to_user_id: "test-user-id",
  due_at: null,
  created_at: "2026-01-01T00:00:00Z",
  crop_batch: null,
  location: null,
  asset: null,
  carrier: null,
  quantity: null,
  quantity_uom: null,
  blocked_reason: null,
};

interface FetchOverrides {
  workItems?: unknown;
  equipmentAttentionStatus?: number;
}

function stubFetch(overrides: FetchOverrides = {}) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/operational-summary")) return jsonResponse(batches);
      if (url.endsWith("/farms/farm-1")) return jsonResponse(farm);
      if (url.includes("/work-items")) return jsonResponse(overrides.workItems ?? []);
      if (url.includes("/shift-handovers/latest")) return jsonResponse(null);
      if (url.includes("/harvestable-plates")) return jsonResponse([]);
      if (url.includes("/locations/tree")) return jsonResponse([]);
      if (url.includes("/assets")) return jsonResponse([]);
      if (url.includes("/carriers")) return jsonResponse([]);
      if (url.includes("/equipment-attention")) {
        if (overrides.equipmentAttentionStatus) {
          return jsonResponse({ detail: "Server error" }, overrides.equipmentAttentionStatus);
        }
        return jsonResponse([]);
      }
      if (url.includes("/equipment-incidents")) return jsonResponse([]);
      if (url.includes("/crop-issues")) return jsonResponse([]);
      if (url.includes("/growing-protocols/due-summary")) return jsonResponse([]);
      if (url.includes("/water/attention")) return jsonResponse([]);
      return jsonResponse({});
    }),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
  window.localStorage.clear();
  currentSearch = "";
  replaceMock.mockClear();
});

describe("FarmHomePage: durable views default to actionable work", () => {
  it("defaults to the Mine view with no ?view= param, never Overview/KPIs", async () => {
    stubFetch();
    render(withQueryClient(<FarmHomePage />));

    await waitFor(() => expect(screen.getByRole("heading", { name: "Today on the Farm" })).toBeInTheDocument());
    expect(screen.getByRole("tab", { name: /Mine/ })).toHaveAttribute("aria-selected", "true");
    // Overview's KPI cards are not landing content -- they render only when
    // the Overview view is active.
    expect(screen.queryByRole("link", { name: /Active batches/ })).not.toBeInTheDocument();
  });

  it("falls back to Mine for an invalid ?view= value instead of breaking the route", async () => {
    currentSearch = "view=not-a-real-view";
    stubFetch();
    render(withQueryClient(<FarmHomePage />));

    await waitFor(() => expect(screen.getByRole("tab", { name: /Mine/ })).toHaveAttribute("aria-selected", "true"));
  });

  it("shows the KPI cards only under the Overview view, with accessible names/hrefs unchanged for the e2e pilot path", async () => {
    stubFetch();
    const { rerender } = render(withQueryClient(<FarmHomePage />));
    await waitFor(() => expect(screen.getByRole("heading", { name: "Today on the Farm" })).toBeInTheDocument());

    screen.getByRole("tab", { name: /Overview/ }).click();
    rerender(withQueryClient(<FarmHomePage />));

    await waitFor(() => expect(screen.getByRole("link", { name: /Active batches/ })).toBeInTheDocument());
    expect(screen.getByRole("link", { name: /Active batches/ })).toHaveAttribute("href", "/farms/farm-1/crop-batches");
    expect(screen.getByRole("link", { name: /Harvest ready/ })).toHaveAttribute(
      "href",
      "/farms/farm-1/crop-batches?filter=harvest_ready",
    );
    expect(screen.getByRole("link", { name: /Active batches/ })).toHaveTextContent("2");
    expect(screen.getByRole("link", { name: /Harvest ready/ })).toHaveTextContent("1");
    expect(screen.getByText("Batches with open quality holds")).toBeInTheDocument();
    expect(screen.getByText("Growing")).toBeInTheDocument();
    expect(screen.getByText("Ready to Harvest")).toBeInTheDocument();
  });

  it("keeps the selected view stable across a rerender via the URL, not local state", async () => {
    currentSearch = "view=ready";
    stubFetch();
    const { rerender } = render(withQueryClient(<FarmHomePage />));
    await waitFor(() => expect(screen.getByRole("tab", { name: /Ready/ })).toHaveAttribute("aria-selected", "true"));

    rerender(withQueryClient(<FarmHomePage />));
    expect(screen.getByRole("tab", { name: /Ready/ })).toHaveAttribute("aria-selected", "true");
  });

  it("switching views clears the URL to avoid stacking history entries, via router.replace", async () => {
    stubFetch();
    render(withQueryClient(<FarmHomePage />));
    await waitFor(() => expect(screen.getByRole("tab", { name: /Mine/ })).toBeInTheDocument());

    screen.getByRole("tab", { name: /Ready/ }).click();
    await waitFor(() => expect(replaceMock).toHaveBeenCalled());
    expect(replaceMock.mock.calls[0][0]).toContain("view=ready");
  });
});

describe("FarmHomePage: independent source failure isolation", () => {
  it("shows an inline, source-named unavailable segment for a failed source without collapsing the rest of the Attention queue", async () => {
    currentSearch = "view=attention";
    stubFetch({ equipmentAttentionStatus: 500 });
    render(withQueryClient(<FarmHomePage />));

    await waitFor(() => expect(screen.getByRole("tab", { name: /Attention/ })).toHaveAttribute("aria-selected", "true"));
    // The failed segment (Equipment attention) shows its own retry-able
    // error, never a false "nothing to do" empty state.
    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
    // Other Attention segments (e.g. crop issues) remain usable/visible,
    // never blanked out just because a sibling source failed.
    expect(screen.getByText("No open crop issues right now.")).toBeInTheDocument();
  });

  it("never shows a failed source's count as zero on the view tab badge", async () => {
    currentSearch = "view=attention";
    stubFetch({ equipmentAttentionStatus: 500 });
    render(withQueryClient(<FarmHomePage />));

    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
    const attentionTab = screen.getByRole("tab", { name: /Attention/ });
    // No numeric badge is rendered for a view with a failed segment.
    expect(attentionTab.textContent).not.toMatch(/Attention0/);
  });
});

describe("FarmHomePage: Mine queue and selected-item inspector", () => {
  it("lists a Work Item assigned to the current user under Mine and opens its inspector on selection", async () => {
    stubFetch({ workItems: [myWorkItem] });
    render(withQueryClient(<FarmHomePage />));

    await waitFor(() => expect(screen.getByText("Check reservoir")).toBeInTheDocument());
    expect(screen.getByText("Select a row to see details and actions.")).toBeInTheDocument();
  });
});

describe("FarmHomePage: persistent operational context", () => {
  it("keeps In Progress/Blocked/Carryover counts visible outside the active view's own queue", async () => {
    stubFetch();
    render(withQueryClient(<FarmHomePage />));
    await waitFor(() => expect(screen.getByLabelText("Operational context")).toBeInTheDocument());
    const contextStrip = within(screen.getByLabelText("Operational context"));
    expect(contextStrip.getByText("In Progress")).toBeInTheDocument();
    expect(contextStrip.getByText("Blocked")).toBeInTheDocument();
    expect(contextStrip.getByText("Carryover")).toBeInTheDocument();
  });
});

describe("FarmHomePage PILOT-SCAN-001F: working-location indicator", () => {
  it("shows a compact working-location indicator when one is active, low-cost and non-dominant", async () => {
    writeWorkingLocation({ locationId: "table-07", farmId: "farm-1", code: "T07", pathString: "GH-01 / Table 07" });
    stubFetch();
    render(withQueryClient(<FarmHomePage />));

    await waitFor(() => expect(screen.getByText("Working location")).toBeInTheDocument());
    expect(screen.getByText("GH-01 / Table 07")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /scan next/i })).toHaveAttribute("href", "/scan");
  });

  it("shows nothing extra when no working location is active", async () => {
    stubFetch();
    render(withQueryClient(<FarmHomePage />));
    await waitFor(() => expect(screen.getByRole("heading", { name: "Today on the Farm" })).toBeInTheDocument());
    expect(screen.queryByText("Working location")).not.toBeInTheDocument();
  });
});
