import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const searchParams = new URLSearchParams();

vi.mock("next/navigation", () => ({
  useParams: () => ({ farmId: "farm-1", entityType: "carrier", entityId: "carrier-1" }),
  useSearchParams: () => searchParams,
}));

import { withQueryClient } from "@/lib/test-utils";

import EquipmentReadinessPage from "./page";

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

let currentState = makeState();
const postedCommandIds: string[] = [];
let markReadyStatus = 200;

function stubFetch() {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (init?.method === "POST" && url.includes("/mark-ready")) {
        const body = JSON.parse(String(init.body));
        postedCommandIds.push(body.client_command_id);
        if (markReadyStatus !== 200) return jsonResponse({ detail: "Conflict" }, markReadyStatus);
        return jsonResponse(currentState);
      }
      if (init?.method === "POST" && url.includes("/mark-awaiting-cleaning")) {
        return jsonResponse(currentState);
      }
      if (url.includes("/readiness/") && url.includes("/history")) return jsonResponse([]);
      if (url.includes("/carriers/carrier-1/readiness")) return jsonResponse(currentState);
      return jsonResponse([]);
    }),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
  Array.from(searchParams.keys()).forEach((key) => searchParams.delete(key));
  postedCommandIds.length = 0;
  markReadyStatus = 200;
});

describe("EquipmentReadinessPage: valid-only actions per the frozen lifecycle rules", () => {
  it("cleaning-required UNKNOWN shows Mark Awaiting Cleaning as primary, never Mark Ready", async () => {
    currentState = makeState({ current_state: "unknown", requires_cleaning: true });
    stubFetch();
    render(withQueryClient(<EquipmentReadinessPage />));
    await waitFor(() => expect(screen.getByRole("button", { name: "Mark Awaiting Cleaning" })).toBeInTheDocument());
    expect(screen.queryByRole("button", { name: "Mark Ready" })).not.toBeInTheDocument();
  });

  it("a Carrier blocked by an active assignment shows the blocker reason and no Mark Ready", async () => {
    currentState = makeState({
      current_state: "cleaning_completed", latest_cleaning_result: "completed", is_in_use: true,
    });
    stubFetch();
    render(withQueryClient(<EquipmentReadinessPage />));
    await waitFor(() => expect(screen.getByText(/cannot be marked Ready while in use/)).toBeInTheDocument());
    expect(screen.queryByRole("button", { name: "Mark Ready" })).not.toBeInTheDocument();
  });

  it("NEEDS_REWORK shows the blocker reason and offers only the re-clean path, never Mark Ready", async () => {
    currentState = makeState({ current_state: "cleaning_completed", latest_cleaning_result: "needs_rework" });
    stubFetch();
    render(withQueryClient(<EquipmentReadinessPage />));
    await waitFor(() => expect(screen.getByText(/Needs Rework/)).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Mark Awaiting Cleaning" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Mark Ready" })).not.toBeInTheDocument();
  });

  it("RETIRED shows no action controls at all", async () => {
    currentState = makeState({ current_state: "retired" });
    stubFetch();
    render(withQueryClient(<EquipmentReadinessPage />));
    await waitFor(() => expect(screen.getByText(/Retired — terminal/)).toBeInTheDocument());
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("a `?action=` deep link pre-opens that exact valid command", async () => {
    currentState = makeState({ current_state: "awaiting_cleaning" });
    searchParams.set("action", "record_cleaning");
    stubFetch();
    render(withQueryClient(<EquipmentReadinessPage />));
    await waitFor(() => expect(screen.getByLabelText("Effective at")).toBeInTheDocument());
  });
});

describe("EquipmentReadinessPage: stable command identity across a same-payload retry", () => {
  it("reuses the same client_command_id when Mark Ready is retried after a failed attempt", async () => {
    currentState = makeState({ current_state: "unknown", requires_cleaning: false, is_in_use: null });
    markReadyStatus = 409;
    stubFetch();
    render(withQueryClient(<EquipmentReadinessPage />));

    // Opens the confirm panel (mints the command identity for this attempt).
    await waitFor(() => expect(screen.getByRole("button", { name: "Mark Ready" })).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Mark Ready" }));
    await waitFor(() => expect(screen.getByText("Note (optional)")).toBeInTheDocument());

    // First submit attempt -- fails (409), panel stays open with the error.
    fireEvent.click(screen.getByRole("button", { name: "Mark Ready" }));
    await waitFor(() => expect(postedCommandIds).toHaveLength(1));
    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());

    // Retry the same command after the failure -- must reuse the exact
    // same client_command_id, never mint a new one for a retry.
    fireEvent.click(screen.getByRole("button", { name: "Mark Ready" }));
    await waitFor(() => expect(postedCommandIds).toHaveLength(2));
    expect(postedCommandIds[0]).toBe(postedCommandIds[1]);
  });

  it("mints a new client_command_id only after cancelling and reopening the action", async () => {
    currentState = makeState({ current_state: "unknown", requires_cleaning: false, is_in_use: null });
    markReadyStatus = 409;
    stubFetch();
    render(withQueryClient(<EquipmentReadinessPage />));

    await waitFor(() => expect(screen.getByRole("button", { name: "Mark Ready" })).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Mark Ready" }));
    await waitFor(() => expect(screen.getByText("Note (optional)")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Mark Ready" }));
    await waitFor(() => expect(postedCommandIds).toHaveLength(1));

    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Mark Ready" })).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Mark Ready" }));
    await waitFor(() => expect(screen.getByText("Note (optional)")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Mark Ready" }));
    await waitFor(() => expect(postedCommandIds).toHaveLength(2));
    expect(postedCommandIds[0]).not.toBe(postedCommandIds[1]);
  });
});
