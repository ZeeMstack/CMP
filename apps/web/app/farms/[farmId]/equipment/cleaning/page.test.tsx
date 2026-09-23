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
  usePathname: () => "/farms/farm-1/equipment/cleaning",
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

import EquipmentCleaningQueuePage from "./page";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

function makeState(overrides: Record<string, unknown> = {}) {
  return {
    id: "state-1", tenant_id: "t1", farm_id: "farm-1", entity_type: "carrier",
    asset_id: null, carrier_id: "carrier-1", current_state: "unknown",
    state_changed_at: "2026-01-01T00:00:00Z", state_changed_by_user_id: null,
    state_note: null, last_cleaning_event_id: null,
    created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z",
    entity_code: "ST-0001", entity_name: null, equipment_type_code: "seed_tray", equipment_type_name: "Seed Tray",
    requires_cleaning: true, is_in_use: false, latest_cleaning_result: null,
    ...overrides,
  };
}

function stubFetch(byState: Record<string, unknown[]>) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = new URL(String(input), "http://localhost");
      if (url.pathname.endsWith("/equipment-readiness")) {
        const states = url.searchParams.getAll("state");
        const key = states.join(",");
        return jsonResponse(byState[key] ?? []);
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

describe("EquipmentCleaningQueuePage: durable views over the real lifecycle states", () => {
  it("defaults to Unassessed (UNKNOWN) and switches views via URL state", async () => {
    stubFetch({
      unknown: [makeState({ id: "s-unknown", entity_code: "ST-UNKNOWN" })],
      awaiting_cleaning: [makeState({ id: "s-cleaning", entity_code: "ST-CLEANING", current_state: "awaiting_cleaning" })],
    });
    render(withQueryClient(<EquipmentCleaningQueuePage />));

    await waitFor(() => expect(screen.getByRole("tab", { name: "Unassessed" })).toHaveAttribute("aria-selected", "true"));
    await waitFor(() => expect(screen.getByText("ST-UNKNOWN")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("tab", { name: "Cleaning" }));
    await waitFor(() => expect(screen.getByText("ST-CLEANING")).toBeInTheDocument());
    expect(screen.queryByText("ST-UNKNOWN")).not.toBeInTheDocument();
  });

  it("Attention view lists both DAMAGED and MAINTENANCE items", async () => {
    currentSearch = "view=attention";
    stubFetch({
      "damaged,maintenance": [
        makeState({ id: "s-damaged", entity_code: "ST-DAMAGED", current_state: "damaged" }),
        makeState({ id: "s-maint", entity_code: "ST-MAINT", current_state: "maintenance" }),
      ],
    });
    render(withQueryClient(<EquipmentCleaningQueuePage />));
    await waitFor(() => expect(screen.getByText("ST-DAMAGED")).toBeInTheDocument());
    expect(screen.getByText("ST-MAINT")).toBeInTheDocument();
  });

  it("cleaning-required UNKNOWN row's inspector never offers Mark Ready", async () => {
    stubFetch({ unknown: [makeState({ requires_cleaning: true })] });
    render(withQueryClient(<EquipmentCleaningQueuePage />));
    await waitFor(() => expect(screen.getByRole("button", { name: /ST-0001/ })).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: /ST-0001/ }));
    await waitFor(() => expect(screen.getByRole("link", { name: "Mark Awaiting Cleaning" })).toBeInTheDocument());
    expect(screen.queryByRole("link", { name: "Mark Ready" })).not.toBeInTheDocument();
  });

  it("non-cleaning UNKNOWN row's inspector offers Mark Ready", async () => {
    stubFetch({
      unknown: [makeState({ requires_cleaning: false, entity_type: "asset", asset_id: "asset-1", carrier_id: null, is_in_use: null })],
    });
    render(withQueryClient(<EquipmentCleaningQueuePage />));
    await waitFor(() => expect(screen.getByRole("button", { name: /ST-0001/ })).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: /ST-0001/ }));
    await waitFor(() => expect(screen.getByRole("link", { name: "Mark Ready" })).toBeInTheDocument());
  });

  it("NEEDS_REWORK row's inspector never offers Mark Ready, offers the re-clean path instead", async () => {
    currentSearch = "view=release";
    stubFetch({
      cleaning_completed: [makeState({ current_state: "cleaning_completed", latest_cleaning_result: "needs_rework" })],
    });
    render(withQueryClient(<EquipmentCleaningQueuePage />));
    await waitFor(() => expect(screen.getByRole("button", { name: /ST-0001/ })).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: /ST-0001/ }));
    await waitFor(() => expect(screen.getByRole("link", { name: "Mark Awaiting Cleaning" })).toBeInTheDocument());
    expect(screen.queryByRole("link", { name: "Mark Ready" })).not.toBeInTheDocument();
  });

  it("shows an empty state distinct from an error state", async () => {
    stubFetch({ unknown: [] });
    render(withQueryClient(<EquipmentCleaningQueuePage />));
    await waitFor(() => expect(screen.getByText("Nothing awaiting an initial assessment.")).toBeInTheDocument());
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
