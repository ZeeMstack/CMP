import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { FarmWorkItemRead } from "@/lib/api/client";
import { DEFAULT_TEST_BOOTSTRAP, withQueryClient } from "@/lib/test-utils";

import { WorkItemRow } from "./WorkItemRow";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

function makeItem(overrides: Partial<FarmWorkItemRead> = {}): FarmWorkItemRead {
  return {
    id: "wi-1",
    tenant_id: "t1",
    farm_id: "farm-1",
    code: "FW-20260914-0001",
    work_type: "cleaning",
    category: "cleaning",
    title: "Clean Trolley",
    instructions: null,
    status: "open",
    priority: "normal",
    due_at: null,
    assigned_to_user_id: null,
    crop_batch: null,
    location: null,
    carrier: null,
    asset: null,
    quantity: null,
    quantity_uom: null,
    completion_mode: "manual_record",
    result_entity_type: null,
    result_entity_id: null,
    result_recorded_at: null,
    completed_by_user_id: null,
    completed_at: null,
    completion_note: null,
    blocked_reason: null,
    blocked_at: null,
    blocked_by_user_id: null,
    cancelled_at: null,
    cancelled_by_user_id: null,
    cancel_reason: null,
    created_by_user_id: "u1",
    created_at: "2026-09-14T06:00:00Z",
    updated_at: "2026-09-14T06:00:00Z",
    ...overrides,
  };
}

function renderRow(item: FarmWorkItemRead) {
  return render(
    withQueryClient(
      <table>
        <tbody>
          <WorkItemRow item={item} farmId="farm-1" currentUserId={DEFAULT_TEST_BOOTSTRAP.user!.id} />
        </tbody>
      </table>,
    ),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("WorkItemRow", () => {
  it("shows a Start action for an open, unassigned item and calls the start endpoint", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/start")) return jsonResponse(makeItem({ status: "in_progress" }));
      return jsonResponse({});
    });
    vi.stubGlobal("fetch", fetchMock);

    renderRow(makeItem());
    fireEvent.click(screen.getByRole("button", { name: "Start" }));

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining("/farms/farm-1/work-items/wi-1/start"),
        expect.objectContaining({ method: "POST" }),
      ),
    );
  });

  it("does not offer Start for an item assigned to someone else", () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({})));
    renderRow(makeItem({ assigned_to_user_id: "someone-else" }));
    expect(screen.queryByRole("button", { name: "Start" })).not.toBeInTheDocument();
  });

  it("blocked work requires a reason -- Confirm is rejected with an empty reason and never calls the endpoint", async () => {
    const fetchMock = vi.fn(async () => jsonResponse(makeItem({ status: "blocked" })));
    vi.stubGlobal("fetch", fetchMock);

    renderRow(makeItem({ status: "in_progress" }));
    fireEvent.click(screen.getByRole("button", { name: "Block" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));

    expect(await screen.findByText("Reason is required")).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalledWith(expect.stringContaining("/block"), expect.anything());
  });

  it("blocking with a reason calls the block endpoint with that reason", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/block")) {
        const body = JSON.parse(String(init?.body));
        expect(body.reason).toBe("destination full");
        return jsonResponse(makeItem({ status: "blocked", blocked_reason: "destination full" }));
      }
      return jsonResponse({});
    });
    vi.stubGlobal("fetch", fetchMock);

    renderRow(makeItem({ status: "in_progress" }));
    fireEvent.click(screen.getByRole("button", { name: "Block" }));
    fireEvent.change(screen.getByPlaceholderText("Reason (required)"), { target: { value: "destination full" } });
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining("/block"), expect.anything()));
  });

  it("shows Resume (never Block/Start) for a blocked item, with its reason visible", () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({})));
    renderRow(makeItem({ status: "blocked", blocked_reason: "equipment unavailable" }));
    expect(screen.getByRole("button", { name: "Resume" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Start" })).not.toBeInTheDocument();
    expect(screen.getByText("equipment unavailable")).toBeInTheDocument();
  });

  it("never offers a Complete action for an OPERATIONAL_RECORD item", () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({})));
    renderRow(makeItem({ completion_mode: "operational_record", status: "in_progress" }));
    expect(screen.queryByRole("button", { name: "Complete" })).not.toBeInTheDocument();
  });

  it("offers Complete for a MANUAL_RECORD item and calls the complete endpoint", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/complete")) return jsonResponse(makeItem({ status: "completed" }));
      return jsonResponse({});
    });
    vi.stubGlobal("fetch", fetchMock);

    renderRow(makeItem({ status: "in_progress" }));
    fireEvent.click(screen.getByRole("button", { name: "Complete" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining("/complete"), expect.anything()),
    );
  });

  it("shows an Open Observation link for an operational_record observation item with batch context", () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({})));
    renderRow(
      makeItem({
        completion_mode: "operational_record",
        work_type: "observation",
        crop_batch: { id: "batch-1", code: "B-001" },
      }),
    );
    const link = screen.getByRole("link", { name: "Open Observation" });
    expect(link).toHaveAttribute("href", "/farms/farm-1/observations?batchId=batch-1&workItemId=wi-1");
  });

  it("shows an Open Harvest link for an operational_record harvest item with batch context", () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({})));
    renderRow(
      makeItem({
        completion_mode: "operational_record",
        work_type: "harvest",
        crop_batch: { id: "batch-2", code: "B-002" },
      }),
    );
    const link = screen.getByRole("link", { name: "Open Harvest" });
    expect(link).toHaveAttribute("href", "/farms/farm-1/leafy-production/harvest?batchId=batch-2&workItemId=wi-1");
  });

  it("displays every structured context piece the item carries, never a placeholder for one that doesn't apply", () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({})));
    renderRow(
      makeItem({
        crop_batch: { id: "batch-3", code: "B-LET-2026-014" },
        location: { id: "loc-1", code: "GH-01", name: "Table 07" },
      }),
    );
    expect(screen.getByText("Batch B-LET-2026-014")).toBeInTheDocument();
    expect(screen.getByText("GH-01 Table 07")).toBeInTheDocument();
    // No asset/carrier context on this item -- the Context cell (index 1)
    // renders nothing for them, and no fallback "—" either since real
    // context IS present (the Due column's own, unrelated "—" is fine).
    const contextCell = screen.getAllByRole("cell")[1];
    expect(contextCell.textContent).not.toContain("—");
  });

  it("shows a plain em dash in the Context cell only when no structured context applies at all", () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({})));
    renderRow(makeItem());
    const contextCell = screen.getAllByRole("cell")[1];
    expect(contextCell.textContent).toBe("—");
  });
});
