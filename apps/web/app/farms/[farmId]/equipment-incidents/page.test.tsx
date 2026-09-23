import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useSyncExternalStore } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { withQueryClient } from "@/lib/test-utils";

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
  usePathname: () => "/farms/farm-1/equipment-incidents",
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

import EquipmentIncidentsPage from "./page";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

function makeIncident(overrides: Record<string, unknown> = {}) {
  return {
    id: "inc-1", tenant_id: "t1", farm_id: "farm-1", code: "EI-20260101-0001",
    asset_id: "asset-1", asset: { id: "asset-1", code: "GT-01", name: "Trolley 1", criticality: "normal" },
    location_id: null, location: null,
    potentially_impacted_location_id: "loc-2",
    potentially_impacted_location: { id: "loc-2", code: "GH-01", name: "Greenhouse 1" },
    severity: "high", category: "cooling", description: "Compressor failure", detected_by_user_id: "u1",
    detected_at: "2026-01-01T00:00:00Z", notes: null,
    status: "open", opened_by_user_id: "u1", opened_at: "2026-01-01T00:05:00Z",
    assigned_owner_user_id: null, acknowledged_by_user_id: null, acknowledged_at: null,
    resolved_by_user_id: null, resolved_at: null, resolution_note: null,
    closed_by_user_id: null, closed_at: null, close_note: null, updated_at: "2026-01-01T00:05:00Z",
    ...overrides,
  };
}

function stubFetch(byStatusKey: Record<string, unknown[]>) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = new URL(String(input), "http://localhost");
      if (url.pathname.endsWith("/equipment-incidents")) {
        const key = url.searchParams.getAll("status").join(",");
        return jsonResponse(byStatusKey[key] ?? []);
      }
      return jsonResponse([]);
    }),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
  currentSearch = "";
  replaceMock.mockClear();
});

describe("EquipmentIncidentsPage: durable queue/list-detail workspace", () => {
  it("defaults to the Open view", async () => {
    stubFetch({ "open,acknowledged,action_in_progress": [makeIncident()] });
    render(withQueryClient(<EquipmentIncidentsPage />));
    await waitFor(() => expect(screen.getByRole("tab", { name: /Open/ })).toHaveAttribute("aria-selected", "true"));
    await waitFor(() => expect(screen.getByText("EI-20260101-0001")).toBeInTheDocument());
  });

  it("switches to Resolved & Closed via the view tab", async () => {
    stubFetch({
      "open,acknowledged,action_in_progress": [],
      "resolved,closed": [makeIncident({ id: "inc-2", code: "EI-20260101-0002", status: "closed" })],
    });
    render(withQueryClient(<EquipmentIncidentsPage />));
    await waitFor(() => expect(screen.getByRole("tab", { name: /Open/ })).toBeInTheDocument());

    fireEvent.click(screen.getByRole("tab", { name: /Resolved/ }));
    await waitFor(() => expect(screen.getByText("EI-20260101-0002")).toBeInTheDocument());
  });

  it("selecting a row opens the inspector showing Potentially impacted area, never 'Affected crop'", async () => {
    stubFetch({ "open,acknowledged,action_in_progress": [makeIncident()] });
    render(withQueryClient(<EquipmentIncidentsPage />));
    await waitFor(() => expect(screen.getByText("EI-20260101-0001")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: /EI-20260101-0001/ }));
    await waitFor(() => expect(screen.getByText("Potentially impacted area")).toBeInTheDocument());
    expect(screen.queryByText(/Affected crop/i)).not.toBeInTheDocument();
  });

  it("shows an empty state distinct from an error", async () => {
    stubFetch({ "open,acknowledged,action_in_progress": [] });
    render(withQueryClient(<EquipmentIncidentsPage />));
    await waitFor(() => expect(screen.getByText("Nothing here")).toBeInTheDocument());
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
