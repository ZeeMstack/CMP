import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { FarmWorkItemRead } from "@/lib/api/client";
import { withQueryClient } from "@/lib/test-utils";

import { WorkItemActions } from "./WorkItemActions";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

function makeItem(overrides: Partial<FarmWorkItemRead> = {}): FarmWorkItemRead {
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

function postedBodiesFor(fetchMock: ReturnType<typeof vi.fn>, suffix: string) {
  return fetchMock.mock.calls
    .filter(([url, init]) => String(url).endsWith(suffix) && init?.method === "POST")
    .map(([, init]) => JSON.parse(String(init?.body)));
}

/** Renders with `key={item.id}` at the same position `WorkItemRow`/
 * `WorkItemInspectorPanel` do (R2), so a `rerender` with a different
 * `item` exercises the same remount-on-selection-change behavior those
 * call sites rely on. */
function renderActions(item: FarmWorkItemRead) {
  return render(
    withQueryClient(<WorkItemActions key={item.id} item={item} farmId="farm-1" currentUserId="me" />),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("WorkItemActions: R2 frozen-payload retry/idempotency contract (Start)", () => {
  it("a network failure retry resends the exact same client_command_id", async () => {
    let call = 0;
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/start") && init?.method === "POST") {
        call += 1;
        if (call === 1) throw new TypeError("Failed to fetch");
        return jsonResponse(makeItem({ status: "in_progress" }));
      }
      return jsonResponse({});
    });
    vi.stubGlobal("fetch", fetchMock);
    renderActions(makeItem());

    fireEvent.click(screen.getByRole("button", { name: "Start" }));
    await waitFor(() => expect(postedBodiesFor(fetchMock, "/start")).toHaveLength(1));
    expect(await screen.findByRole("button", { name: "Retry" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(postedBodiesFor(fetchMock, "/start")).toHaveLength(2));

    const [first, second] = postedBodiesFor(fetchMock, "/start");
    expect(second).toEqual(first);
  });

  it("a definitive rejection (409 conflict) followed by a new click mints a new client_command_id", async () => {
    let call = 0;
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/start") && init?.method === "POST") {
        call += 1;
        if (call === 1) return jsonResponse({ detail: "Already started" }, 409);
        return jsonResponse(makeItem({ status: "in_progress" }));
      }
      return jsonResponse({});
    });
    vi.stubGlobal("fetch", fetchMock);
    renderActions(makeItem());

    fireEvent.click(screen.getByRole("button", { name: "Start" }));
    await waitFor(() => expect(postedBodiesFor(fetchMock, "/start")).toHaveLength(1));
    // Definitive rejection -- the button stays labeled Start, never Retry.
    expect(await screen.findByRole("button", { name: "Start" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Start" }));
    await waitFor(() => expect(postedBodiesFor(fetchMock, "/start")).toHaveLength(2));

    const [first, second] = postedBodiesFor(fetchMock, "/start");
    expect(second.client_command_id).not.toBe(first.client_command_id);
  });
});

describe("WorkItemActions: R2 frozen-payload retry/idempotency contract (Block)", () => {
  it("a network failure retry resends the exact same client_command_id and reason", async () => {
    let call = 0;
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/block") && init?.method === "POST") {
        call += 1;
        if (call === 1) throw new TypeError("Failed to fetch");
        return jsonResponse(makeItem({ status: "blocked", blocked_reason: "destination full" }));
      }
      return jsonResponse({});
    });
    vi.stubGlobal("fetch", fetchMock);
    renderActions(makeItem({ status: "in_progress" }));

    fireEvent.click(screen.getByRole("button", { name: "Block" }));
    fireEvent.change(screen.getByPlaceholderText("Reason (required)"), { target: { value: "destination full" } });
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
    await waitFor(() => expect(postedBodiesFor(fetchMock, "/block")).toHaveLength(1));
    expect(await screen.findByRole("button", { name: "Retry" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(postedBodiesFor(fetchMock, "/block")).toHaveLength(2));

    const [first, second] = postedBodiesFor(fetchMock, "/block");
    expect(second).toEqual(first);
    expect(first.reason).toBe("destination full");
  });

  it("an attempted reason edit while uncertain does not change what Retry resends", async () => {
    let call = 0;
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/block") && init?.method === "POST") {
        call += 1;
        if (call === 1) return new Response("", { status: 500 });
        return jsonResponse(makeItem({ status: "blocked" }));
      }
      return jsonResponse({});
    });
    vi.stubGlobal("fetch", fetchMock);
    renderActions(makeItem({ status: "in_progress" }));

    fireEvent.click(screen.getByRole("button", { name: "Block" }));
    fireEvent.change(screen.getByPlaceholderText("Reason (required)"), { target: { value: "Original reason" } });
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
    await waitFor(() => expect(postedBodiesFor(fetchMock, "/block")).toHaveLength(1));
    await screen.findByRole("button", { name: "Retry" });

    expect(screen.getByPlaceholderText("Reason (required)")).toHaveAttribute("readonly");
    fireEvent.change(screen.getByPlaceholderText("Reason (required)"), {
      target: { value: "Edited reason that must never be sent" },
    });

    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(postedBodiesFor(fetchMock, "/block")).toHaveLength(2));

    const [first, second] = postedBodiesFor(fetchMock, "/block");
    expect(second.reason).toBe("Original reason");
    expect(second.client_command_id).toBe(first.client_command_id);
  });

  it("Cancel out of an uncertain Block attempt, then a fresh Block, mints a new client_command_id", async () => {
    let call = 0;
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/block") && init?.method === "POST") {
        call += 1;
        if (call === 1) throw new TypeError("Failed to fetch");
        return jsonResponse(makeItem({ status: "blocked" }));
      }
      return jsonResponse({});
    });
    vi.stubGlobal("fetch", fetchMock);
    renderActions(makeItem({ status: "in_progress" }));

    fireEvent.click(screen.getByRole("button", { name: "Block" }));
    fireEvent.change(screen.getByPlaceholderText("Reason (required)"), { target: { value: "First reason" } });
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
    await waitFor(() => expect(postedBodiesFor(fetchMock, "/block")).toHaveLength(1));
    await screen.findByRole("button", { name: "Retry" });

    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    // Back to the idle action row.
    expect(await screen.findByRole("button", { name: "Block" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Block" }));
    fireEvent.change(screen.getByPlaceholderText("Reason (required)"), { target: { value: "Second reason" } });
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
    await waitFor(() => expect(postedBodiesFor(fetchMock, "/block")).toHaveLength(2));

    const [first, second] = postedBodiesFor(fetchMock, "/block");
    expect(second.client_command_id).not.toBe(first.client_command_id);
    expect(second.reason).toBe("Second reason");
  });
});

describe("WorkItemActions: R2 per-item command scoping", () => {
  it("a failed Start for Work Item A cannot reuse its client_command_id for Work Item B", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/start")) return new Response("", { status: 500 });
      return jsonResponse({});
    });
    vi.stubGlobal("fetch", fetchMock);

    const itemA = makeItem({ id: "wi-a" });
    const itemB = makeItem({ id: "wi-b" });
    const { rerender } = renderActions(itemA);

    fireEvent.click(screen.getByRole("button", { name: "Start" }));
    await waitFor(() => expect(postedBodiesFor(fetchMock, "/start")).toHaveLength(1));
    // Item A is now uncertain -- its own button relabels to Retry.
    await screen.findByRole("button", { name: "Retry" });

    // Selecting a different Work Item remounts WorkItemActions (key
    // changes from wi-a to wi-b) -- its own frozen attempt starts fresh.
    rerender(withQueryClient(<WorkItemActions key={itemB.id} item={itemB} farmId="farm-1" currentUserId="me" />));
    expect(await screen.findByRole("button", { name: "Start" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Start" }));
    await waitFor(() => expect(postedBodiesFor(fetchMock, "/start")).toHaveLength(2));

    const [forA, forB] = postedBodiesFor(fetchMock, "/start");
    expect(forB.client_command_id).not.toBe(forA.client_command_id);
  });
});
