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

// UX-OPS-001B R1 (blocker #3): `available_actions`/`primary_action` are now
// computed once, backend-side, by
// `equipment_readiness_service.compute_readiness_actions` -- these fixtures
// hard-code the exact value the real backend would compute for each
// scenario below (mirroring apps/api/tests/test_equipment_readiness_actions.py's
// own hard-coded expectations) rather than recomputing it here, which would
// recreate the very duplicated transition table this change removed.
function makeState(overrides: Record<string, unknown> = {}) {
  return {
    id: "state-1", tenant_id: "t1", farm_id: "farm-1", entity_type: "carrier",
    asset_id: null, carrier_id: "carrier-1", current_state: "unknown",
    state_changed_at: "2026-01-01T00:00:00Z", state_changed_by_user_id: null,
    state_note: null, last_cleaning_event_id: null,
    created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z",
    entity_code: "ST-0001", entity_name: null, equipment_type_code: "seed_tray", equipment_type_name: "Seed Tray",
    requires_cleaning: true, is_in_use: false, latest_cleaning_result: null,
    available_actions: ["mark_awaiting_cleaning", "report_damage", "send_to_maintenance", "retire"],
    primary_action: "mark_awaiting_cleaning",
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
      awaiting_cleaning: [
        makeState({
          id: "s-cleaning", entity_code: "ST-CLEANING", current_state: "awaiting_cleaning",
          available_actions: ["record_cleaning", "report_damage", "send_to_maintenance", "retire"],
          primary_action: "record_cleaning",
        }),
      ],
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
        makeState({
          id: "s-damaged", entity_code: "ST-DAMAGED", current_state: "damaged",
          available_actions: ["send_to_maintenance", "retire"], primary_action: null,
        }),
        makeState({
          id: "s-maint", entity_code: "ST-MAINT", current_state: "maintenance",
          available_actions: ["return_from_maintenance", "report_damage", "retire"],
          primary_action: "return_from_maintenance",
        }),
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
      unknown: [
        makeState({
          requires_cleaning: false, entity_type: "asset", asset_id: "asset-1", carrier_id: null, is_in_use: null,
          available_actions: ["mark_ready", "report_damage", "send_to_maintenance", "retire"],
          primary_action: "mark_ready",
        }),
      ],
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

  it("R1-6: a COMPLETED row and a NEEDS_REWORK row are visually distinct before either is selected", async () => {
    currentSearch = "view=release";
    stubFetch({
      cleaning_completed: [
        makeState({
          id: "s-completed", entity_code: "ST-COMPLETED", current_state: "cleaning_completed",
          latest_cleaning_result: "completed",
        }),
        makeState({
          id: "s-rework", entity_code: "ST-REWORK", current_state: "cleaning_completed",
          latest_cleaning_result: "needs_rework",
        }),
      ],
    });
    render(withQueryClient(<EquipmentCleaningQueuePage />));
    await waitFor(() => expect(screen.getByText("ST-COMPLETED")).toBeInTheDocument());

    // Both rows share the same `current_state` badge ("Cleaning completed")
    // but each also carries its own distinct cleaning-result badge -- never
    // identical until a row is opened in the inspector.
    expect(screen.getAllByText("Cleaning completed")).toHaveLength(2);
    expect(screen.getByText("Completed")).toBeInTheDocument();
    expect(screen.getByText("Needs rework")).toBeInTheDocument();
  });
});
