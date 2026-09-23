import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useParams: () => ({ farmId: "farm-1", incidentId: "inc-1" }),
}));

import { withQueryClient } from "@/lib/test-utils";

import EquipmentIncidentWorkspacePage from "./page";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

function makeIncident(overrides: Record<string, unknown> = {}) {
  return {
    id: "inc-1", tenant_id: "t1", farm_id: "farm-1", code: "EI-20260101-0001",
    asset_id: "asset-1", asset: { id: "asset-1", code: "GT-01", name: "Trolley 1", criticality: "normal" },
    location_id: null, location: null,
    potentially_impacted_location_id: null, potentially_impacted_location: null,
    severity: "high", category: "cooling", description: "Compressor failure", detected_by_user_id: "u1",
    detected_at: "2026-01-01T00:00:00Z", notes: null,
    status: "open", opened_by_user_id: "u1", opened_at: "2026-01-01T00:05:00Z",
    assigned_owner_user_id: null, acknowledged_by_user_id: null, acknowledged_at: null,
    resolved_by_user_id: null, resolved_at: null, resolution_note: null,
    closed_by_user_id: null, closed_at: null, close_note: null, updated_at: "2026-01-01T00:05:00Z",
    ...overrides,
  };
}

let currentIncident = makeIncident();
const postedCommandIds: string[] = [];
let acknowledgeStatus = 200;

function stubFetch() {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (init?.method === "POST" && url.includes("/acknowledge")) {
        const body = JSON.parse(String(init.body));
        postedCommandIds.push(body.client_command_id);
        if (acknowledgeStatus !== 200) return jsonResponse({ detail: "Conflict" }, acknowledgeStatus);
        return jsonResponse({ ...currentIncident, status: "acknowledged" });
      }
      if (init?.method === "POST" && url.includes("/work-items")) {
        return jsonResponse({
          id: "wi-1", code: "WI-001", title: "Fix compressor", status: "open", priority: "normal",
          work_type: "other", completion_mode: "manual_record", assigned_to_user_id: null, due_at: null,
          created_at: "2026-01-01T00:00:00Z", crop_batch: null, location: null, asset: null, carrier: null,
          quantity: null, quantity_uom: null, blocked_reason: null,
        }, 201);
      }
      if (url.includes("/history")) return jsonResponse([]);
      if (url.includes("/equipment-incidents/inc-1")) return jsonResponse(currentIncident);
      return jsonResponse([]);
    }),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
  postedCommandIds.length = 0;
  acknowledgeStatus = 200;
});

describe("EquipmentIncidentWorkspacePage: consolidated Status panel", () => {
  it("OPEN shows Acknowledge as the primary next action", async () => {
    currentIncident = makeIncident({ status: "open" });
    stubFetch();
    render(withQueryClient(<EquipmentIncidentWorkspacePage />));
    await waitFor(() => expect(screen.getByRole("button", { name: "Acknowledge" })).toBeInTheDocument());
  });

  it("CLOSED shows no action controls", async () => {
    currentIncident = makeIncident({ status: "closed", closed_at: "2026-01-02T00:00:00Z" });
    stubFetch();
    render(withQueryClient(<EquipmentIncidentWorkspacePage />));
    await waitFor(() => expect(screen.getAllByText(/Closed/).length).toBeGreaterThan(0));
    expect(screen.queryByRole("button", { name: /Acknowledge|Resolve|Close Incident/ })).not.toBeInTheDocument();
  });

  it("reuses the same client_command_id across a retry of the same Acknowledge attempt", async () => {
    currentIncident = makeIncident({ status: "open" });
    acknowledgeStatus = 409;
    stubFetch();
    render(withQueryClient(<EquipmentIncidentWorkspacePage />));

    await waitFor(() => expect(screen.getByRole("button", { name: "Acknowledge" })).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Acknowledge" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Confirm Acknowledge" })).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Confirm Acknowledge" }));
    await waitFor(() => expect(postedCommandIds).toHaveLength(1));

    fireEvent.click(screen.getByRole("button", { name: "Confirm Acknowledge" }));
    await waitFor(() => expect(postedCommandIds).toHaveLength(2));
    expect(postedCommandIds[0]).toBe(postedCommandIds[1]);
  });
});

describe("EquipmentIncidentWorkspacePage: Incident vs Work Item resolution boundary", () => {
  it("completing corrective work never visually or behaviorally resolves the Incident", async () => {
    currentIncident = makeIncident({ status: "open" });
    stubFetch();
    render(withQueryClient(<EquipmentIncidentWorkspacePage />));
    await waitFor(() => expect(screen.getByRole("button", { name: "Acknowledge" })).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "Assign Corrective Work" }));
    await waitFor(() => expect(screen.getByLabelText(/^title$/i)).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText(/^title$/i), { target: { value: "Fix compressor" } });
    fireEvent.change(screen.getByLabelText(/^work type$/i), { target: { value: "repair" } });
    fireEvent.click(screen.getByRole("button", { name: /create/i }));

    await waitFor(() => expect(screen.getByText(/Fix compressor/)).toBeInTheDocument());
    // The Incident's own Status panel is untouched -- still OPEN, Acknowledge
    // still the offered action, no "resolved" state implied by the linked
    // Work Item existing/being created.
    expect(screen.getByRole("button", { name: "Acknowledge" })).toBeInTheDocument();
    expect(screen.queryByText(/Resolved/)).not.toBeInTheDocument();
  });
});
