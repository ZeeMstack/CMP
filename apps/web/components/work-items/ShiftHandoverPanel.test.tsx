import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { FarmWorkItemRead, ShiftHandoverRead } from "@/lib/api/client";
import { withQueryClient } from "@/lib/test-utils";

import { ShiftHandoverPanel } from "./ShiftHandoverPanel";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

function makeWorkItem(overrides: Partial<FarmWorkItemRead> = {}): FarmWorkItemRead {
  return {
    id: "wi-1", tenant_id: "t1", farm_id: "farm-1", code: "FW-1", work_type: "cleaning",
    category: "cleaning", title: "Clean Trolley", instructions: null, status: "open", priority: "normal",
    due_at: null, assigned_to_user_id: null, crop_batch: null, location: null, carrier: null, asset: null,
    quantity: null, quantity_uom: null, completion_mode: "manual_record", result_entity_type: null,
    result_entity_id: null, result_recorded_at: null, completed_by_user_id: null, completed_at: null,
    completion_note: null, blocked_reason: null, blocked_at: null, blocked_by_user_id: null,
    cancelled_at: null, cancelled_by_user_id: null, cancel_reason: null, created_by_user_id: "u1",
    created_at: "2026-09-14T06:00:00Z", updated_at: "2026-09-14T06:00:00Z",
    ...overrides,
  } as FarmWorkItemRead;
}

function postedShiftHandoverBodies(fetchMock: ReturnType<typeof vi.fn>) {
  return fetchMock.mock.calls
    .filter(([url, init]) => String(url).includes("/shift-handovers") && !String(url).includes("work-items") && init?.method === "POST")
    .map(([, init]) => JSON.parse(String(init?.body)));
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("ShiftHandoverPanel", () => {
  it("shows the latest handover's note without offering to close or edit any Work Item", () => {
    const latest: ShiftHandoverRead = {
      id: "h1", tenant_id: "t1", farm_id: "farm-1", author_user_id: "u1",
      effective_time: "2026-09-14T18:00:00Z", recorded_at: "2026-09-14T18:00:05Z",
      note: "GC-02 pump still needs a look.", work_item_ids: ["wi-1"],
    };
    render(withQueryClient(<ShiftHandoverPanel farmId="farm-1" latest={latest} openWorkItems={[]} />));

    expect(screen.getByText("GC-02 pump still needs a look.")).toBeInTheDocument();
    expect(screen.getByText(/1 item\(s\) flagged/)).toBeInTheDocument();
    // No status/complete/close control is rendered by this panel at all --
    // it is a read display plus a note form, nothing else.
    expect(screen.queryByRole("button", { name: /complete/i })).not.toBeInTheDocument();
  });

  it("shows a truthful 'no handover yet' state rather than an empty note", () => {
    render(withQueryClient(<ShiftHandoverPanel farmId="farm-1" latest={null} openWorkItems={[]} />));
    expect(screen.getByText("No handover recorded yet.")).toBeInTheDocument();
  });

  it("submitting a note posts to the shift-handovers endpoint and never touches a work-item endpoint", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/shift-handovers") && !url.includes("work-items")) {
        return jsonResponse({
          id: "h2", tenant_id: "t1", farm_id: "farm-1", author_user_id: "u1",
          effective_time: "2026-09-14T18:00:00Z", recorded_at: "2026-09-14T18:00:00Z",
          note: "Handover note", work_item_ids: [],
        });
      }
      return jsonResponse({});
    });
    vi.stubGlobal("fetch", fetchMock);

    render(withQueryClient(<ShiftHandoverPanel farmId="farm-1" latest={null} openWorkItems={[]} />));
    fireEvent.click(screen.getByRole("button", { name: "Leave a note" }));
    fireEvent.change(screen.getByPlaceholderText("What should the next shift know?"), {
      target: { value: "Handover note" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save handover" }));

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining("/farms/farm-1/shift-handovers"),
        expect.objectContaining({ method: "POST" }),
      ),
    );
    const calledPaths = fetchMock.mock.calls.map((c) => String(c[0]));
    expect(calledPaths.some((p) => /\/work-items\/.+\/(start|block|complete|cancel)/.test(p))).toBe(false);
  });
});

describe("ShiftHandoverPanel: R2 frozen-payload retry/idempotency contract", () => {
  it("a network failure retry resends the exact same client_command_id, effective_time, note, and work_item_ids", async () => {
    let call = 0;
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.includes("/shift-handovers") && !url.includes("work-items") && init?.method === "POST") {
        call += 1;
        if (call === 1) throw new TypeError("Failed to fetch");
        return jsonResponse({
          id: "h2", tenant_id: "t1", farm_id: "farm-1", author_user_id: "u1",
          effective_time: "2026-09-14T18:00:00Z", recorded_at: "2026-09-14T18:00:00Z",
          note: "Pump still needs a look", work_item_ids: ["wi-1"],
        });
      }
      return jsonResponse({});
    });
    vi.stubGlobal("fetch", fetchMock);

    render(
      withQueryClient(
        <ShiftHandoverPanel farmId="farm-1" latest={null} openWorkItems={[makeWorkItem({ id: "wi-1" })]} />,
      ),
    );
    fireEvent.click(screen.getByRole("button", { name: "Leave a note" }));
    fireEvent.change(screen.getByPlaceholderText("What should the next shift know?"), {
      target: { value: "Pump still needs a look" },
    });
    fireEvent.click(screen.getByLabelText(/Clean Trolley/));
    fireEvent.click(screen.getByRole("button", { name: "Save handover" }));

    await waitFor(() => expect(postedShiftHandoverBodies(fetchMock)).toHaveLength(1));
    // Uncertain outcome -- the button relabels to Retry.
    await screen.findByRole("button", { name: "Retry" });

    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(postedShiftHandoverBodies(fetchMock)).toHaveLength(2));

    const [first, second] = postedShiftHandoverBodies(fetchMock);
    expect(second).toEqual(first);
    expect(first.note).toBe("Pump still needs a look");
    expect(first.work_item_ids).toEqual(["wi-1"]);
  });

  it("an attempted note edit while uncertain does not change what Retry resends", async () => {
    let call = 0;
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.includes("/shift-handovers") && !url.includes("work-items") && init?.method === "POST") {
        call += 1;
        if (call === 1) return new Response("", { status: 500 });
        return jsonResponse({
          id: "h3", tenant_id: "t1", farm_id: "farm-1", author_user_id: "u1",
          effective_time: "2026-09-14T18:00:00Z", recorded_at: "2026-09-14T18:00:00Z",
          note: "Original note", work_item_ids: [],
        });
      }
      return jsonResponse({});
    });
    vi.stubGlobal("fetch", fetchMock);

    render(withQueryClient(<ShiftHandoverPanel farmId="farm-1" latest={null} openWorkItems={[]} />));
    fireEvent.click(screen.getByRole("button", { name: "Leave a note" }));
    fireEvent.change(screen.getByPlaceholderText("What should the next shift know?"), {
      target: { value: "Original note" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save handover" }));
    await waitFor(() => expect(postedShiftHandoverBodies(fetchMock)).toHaveLength(1));
    await screen.findByRole("button", { name: "Retry" });

    // Attempt to edit the note while the outcome is uncertain.
    fireEvent.change(screen.getByPlaceholderText("What should the next shift know?"), {
      target: { value: "Edited note that must never be sent" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(postedShiftHandoverBodies(fetchMock)).toHaveLength(2));

    const [first, second] = postedShiftHandoverBodies(fetchMock);
    expect(second.note).toBe("Original note");
    expect(second.client_command_id).toBe(first.client_command_id);
  });

  it("a definitive rejection (422) followed by resubmission mints a new client_command_id", async () => {
    let call = 0;
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.includes("/shift-handovers") && !url.includes("work-items") && init?.method === "POST") {
        call += 1;
        if (call === 1) return jsonResponse({ detail: "Invalid" }, 422);
        return jsonResponse({
          id: "h4", tenant_id: "t1", farm_id: "farm-1", author_user_id: "u1",
          effective_time: "2026-09-14T18:00:00Z", recorded_at: "2026-09-14T18:00:00Z",
          note: "Retyped note", work_item_ids: [],
        });
      }
      return jsonResponse({});
    });
    vi.stubGlobal("fetch", fetchMock);

    render(withQueryClient(<ShiftHandoverPanel farmId="farm-1" latest={null} openWorkItems={[]} />));
    fireEvent.click(screen.getByRole("button", { name: "Leave a note" }));
    fireEvent.change(screen.getByPlaceholderText("What should the next shift know?"), { target: { value: "First try" } });
    fireEvent.click(screen.getByRole("button", { name: "Save handover" }));
    await waitFor(() => expect(postedShiftHandoverBodies(fetchMock)).toHaveLength(1));

    // A definitive rejection returns to "editing" -- the button stays
    // labeled Save handover (never Retry), and the field is editable again.
    expect(await screen.findByRole("button", { name: "Save handover" })).toBeInTheDocument();
    fireEvent.change(screen.getByPlaceholderText("What should the next shift know?"), { target: { value: "Retyped note" } });
    fireEvent.click(screen.getByRole("button", { name: "Save handover" }));
    await waitFor(() => expect(postedShiftHandoverBodies(fetchMock)).toHaveLength(2));

    const [first, second] = postedShiftHandoverBodies(fetchMock);
    expect(second.client_command_id).not.toBe(first.client_command_id);
    expect(second.note).toBe("Retyped note");
  });

  it("Cancel followed by a new attempt mints a new client_command_id", async () => {
    let call = 0;
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.includes("/shift-handovers") && !url.includes("work-items") && init?.method === "POST") {
        call += 1;
        if (call === 1) throw new TypeError("Failed to fetch");
        return jsonResponse({
          id: "h5", tenant_id: "t1", farm_id: "farm-1", author_user_id: "u1",
          effective_time: "2026-09-14T18:00:00Z", recorded_at: "2026-09-14T18:00:00Z",
          note: "Second attempt", work_item_ids: [],
        });
      }
      return jsonResponse({});
    });
    vi.stubGlobal("fetch", fetchMock);

    render(withQueryClient(<ShiftHandoverPanel farmId="farm-1" latest={null} openWorkItems={[]} />));
    fireEvent.click(screen.getByRole("button", { name: "Leave a note" }));
    fireEvent.change(screen.getByPlaceholderText("What should the next shift know?"), { target: { value: "First attempt" } });
    fireEvent.click(screen.getByRole("button", { name: "Save handover" }));
    await waitFor(() => expect(postedShiftHandoverBodies(fetchMock)).toHaveLength(1));
    await screen.findByRole("button", { name: "Retry" });

    // Cancel out of the uncertain attempt entirely, then start a genuinely
    // new one.
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    fireEvent.click(screen.getByRole("button", { name: "Leave a note" }));
    fireEvent.change(screen.getByPlaceholderText("What should the next shift know?"), { target: { value: "Second attempt" } });
    fireEvent.click(screen.getByRole("button", { name: "Save handover" }));
    await waitFor(() => expect(postedShiftHandoverBodies(fetchMock)).toHaveLength(2));

    const [first, second] = postedShiftHandoverBodies(fetchMock);
    expect(second.client_command_id).not.toBe(first.client_command_id);
  });
});
