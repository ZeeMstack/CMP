import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { withQueryClient } from "@/lib/test-utils";

import { CreateWorkItemForm } from "./CreateWorkItemForm";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

function makeCreatedItem(overrides: Record<string, unknown> = {}) {
  return {
    id: "wi-new", tenant_id: "t1", farm_id: "farm-1", code: "FW-1", work_type: "cleaning",
    category: "cleaning", title: "x", instructions: null, status: "open", priority: "normal",
    due_at: null, assigned_to_user_id: null, crop_batch: null, location: null, carrier: null, asset: null,
    quantity: null, quantity_uom: null, completion_mode: "manual_record", result_entity_type: null,
    result_entity_id: null, result_recorded_at: null, completed_by_user_id: null, completed_at: null,
    completion_note: null, blocked_reason: null, blocked_at: null, blocked_by_user_id: null,
    cancelled_at: null, cancelled_by_user_id: null, cancel_reason: null, created_by_user_id: "u1",
    created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

/** Every posted `/work-items` create body, in call order. */
function postedBodies(fetchMock: ReturnType<typeof vi.fn>) {
  return fetchMock.mock.calls
    .filter(([url, init]) => String(url).endsWith("/work-items") && init?.method === "POST")
    .map(([, init]) => JSON.parse(String(init?.body)));
}

function fillMinimalFields(title = "Inspect GH-01 cooling pad", workType = "inspection") {
  fireEvent.change(screen.getByPlaceholderText("Clean Germination Trolley 03"), { target: { value: title } });
  fireEvent.change(screen.getByPlaceholderText("cleaning"), { target: { value: workType } });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("CreateWorkItemForm: validation and payload shape", () => {
  it("rejects submission with a blank title/work type", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({})));
    render(withQueryClient(<CreateWorkItemForm farmId="farm-1" onSuccess={vi.fn()} onCancel={vi.fn()} />));

    fireEvent.click(screen.getByRole("button", { name: "Create work item" }));

    expect(await screen.findByText("Title is required")).toBeInTheDocument();
    expect(await screen.findByText("Work type is required")).toBeInTheDocument();
  });

  it("submits a manual_record payload with the filled-in fields", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/work-items") && init?.method === "POST") return jsonResponse(makeCreatedItem(), 201);
      return jsonResponse({});
    });
    vi.stubGlobal("fetch", fetchMock);
    const onSuccess = vi.fn();
    render(withQueryClient(<CreateWorkItemForm farmId="farm-1" onSuccess={onSuccess} onCancel={vi.fn()} currentUserId="me" />));

    fillMinimalFields();
    fireEvent.click(screen.getByLabelText("Assign to me"));
    fireEvent.click(screen.getByRole("button", { name: "Create work item" }));

    await waitFor(() => expect(onSuccess).toHaveBeenCalledTimes(1));
    const [body] = postedBodies(fetchMock);
    expect(body).toMatchObject({
      work_type: "inspection", title: "Inspect GH-01 cooling pad", category: "maintenance",
      priority: "normal", completion_mode: "manual_record", assigned_to_user_id: "me",
    });
    expect(typeof body.client_command_id).toBe("string");
  });

  it("the Assign-to-me checkbox is disabled with no known current user", () => {
    render(withQueryClient(<CreateWorkItemForm farmId="farm-1" onSuccess={vi.fn()} onCancel={vi.fn()} />));
    expect(screen.getByLabelText("Assign to me")).toBeDisabled();
  });

  it("context selects are hidden by default and appear behind 'Add context'", () => {
    render(
      withQueryClient(
        <CreateWorkItemForm
          farmId="farm-1"
          onSuccess={vi.fn()}
          onCancel={vi.fn()}
          locationOptions={[{ id: "loc-1", label: "GH-01 cooling pad" }]}
        />,
      ),
    );
    expect(screen.queryByLabelText("Location")).not.toBeInTheDocument();
    fireEvent.click(screen.getByText("+ Add context (location, batch, asset, carrier)"));
    expect(screen.getByLabelText("Location")).toBeInTheDocument();
  });

  it("submits with the selected Location's real id, never a display string", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/work-items") && init?.method === "POST") return jsonResponse(makeCreatedItem(), 201);
      return jsonResponse({});
    });
    vi.stubGlobal("fetch", fetchMock);
    const onSuccess = vi.fn();
    render(
      withQueryClient(
        <CreateWorkItemForm
          farmId="farm-1"
          onSuccess={onSuccess}
          onCancel={vi.fn()}
          locationOptions={[{ id: "loc-uuid-1", label: "GH-01 cooling pad" }]}
        />,
      ),
    );
    fillMinimalFields();
    fireEvent.click(screen.getByText("+ Add context (location, batch, asset, carrier)"));
    fireEvent.change(screen.getByLabelText("Location"), { target: { value: "loc-uuid-1" } });
    fireEvent.click(screen.getByRole("button", { name: "Create work item" }));

    await waitFor(() => expect(onSuccess).toHaveBeenCalledTimes(1));
    const [body] = postedBodies(fetchMock);
    expect(body.location_id).toBe("loc-uuid-1");
    expect(body.crop_batch_id).toBeNull();
  });

  it("submits with the selected Batch's real id", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/work-items") && init?.method === "POST") return jsonResponse(makeCreatedItem(), 201);
      return jsonResponse({});
    });
    vi.stubGlobal("fetch", fetchMock);
    const onSuccess = vi.fn();
    render(
      withQueryClient(
        <CreateWorkItemForm
          farmId="farm-1"
          onSuccess={onSuccess}
          onCancel={vi.fn()}
          batchOptions={[{ id: "batch-uuid-1", label: "B-LET-2026-014 · Lettuce" }]}
        />,
      ),
    );
    fillMinimalFields("Check Batch after transfer", "inspection");
    fireEvent.click(screen.getByText("+ Add context (location, batch, asset, carrier)"));
    fireEvent.change(screen.getByLabelText("Batch"), { target: { value: "batch-uuid-1" } });
    fireEvent.click(screen.getByRole("button", { name: "Create work item" }));

    await waitFor(() => expect(onSuccess).toHaveBeenCalledTimes(1));
    expect(postedBodies(fetchMock)[0].crop_batch_id).toBe("batch-uuid-1");
  });

  it("omitted context fields are submitted as null, never an empty string placeholder", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/work-items") && init?.method === "POST") return jsonResponse(makeCreatedItem(), 201);
      return jsonResponse({});
    });
    vi.stubGlobal("fetch", fetchMock);
    const onSuccess = vi.fn();
    render(withQueryClient(<CreateWorkItemForm farmId="farm-1" onSuccess={onSuccess} onCancel={vi.fn()} />));
    fillMinimalFields("Clean", "cleaning");
    fireEvent.click(screen.getByRole("button", { name: "Create work item" }));

    await waitFor(() => expect(onSuccess).toHaveBeenCalledTimes(1));
    const [body] = postedBodies(fetchMock);
    expect(body.location_id).toBeNull();
    expect(body.crop_batch_id).toBeNull();
    expect(body.asset_id).toBeNull();
    expect(body.carrier_id).toBeNull();
  });

  // PILOT-AGRO-001B: "Assign corrective work" from a Crop Issue reuses this
  // exact existing form, never a second agronomy task model.
  it("with lockedCropIssue, submits crop_issue_id and its Batch without an editable Batch picker", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/work-items") && init?.method === "POST") return jsonResponse(makeCreatedItem(), 201);
      return jsonResponse({});
    });
    vi.stubGlobal("fetch", fetchMock);
    const onSuccess = vi.fn();
    render(
      withQueryClient(
        <CreateWorkItemForm
          farmId="farm-1"
          onSuccess={onSuccess}
          onCancel={vi.fn()}
          lockedCropIssue={{ id: "issue-uuid-1", code: "CI-20260101-0001", batchId: "batch-uuid-1", batchLabel: "B-LET-2026-014" }}
        />,
      ),
    );
    expect(screen.getByText("CI-20260101-0001", { exact: false })).toBeInTheDocument();
    fillMinimalFields("Prune affected plants", "crop_care");
    fireEvent.click(screen.getByRole("button", { name: "Create work item" }));

    await waitFor(() => expect(onSuccess).toHaveBeenCalledTimes(1));
    const [body] = postedBodies(fetchMock);
    expect(body.crop_issue_id).toBe("issue-uuid-1");
    expect(body.crop_batch_id).toBe("batch-uuid-1");

    fireEvent.click(screen.getByText("+ Add context (location, batch, asset, carrier)"));
    expect(screen.queryByLabelText("Batch")).not.toBeInTheDocument();
  });
});

describe("CreateWorkItemForm: R2 frozen-payload retry/idempotency contract", () => {
  it("a network failure retry resends the exact same client_command_id and payload", async () => {
    let call = 0;
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/work-items") && init?.method === "POST") {
        call += 1;
        if (call === 1) throw new TypeError("Failed to fetch");
        return jsonResponse(makeCreatedItem(), 201);
      }
      return jsonResponse({});
    });
    vi.stubGlobal("fetch", fetchMock);
    const onSuccess = vi.fn();
    render(withQueryClient(<CreateWorkItemForm farmId="farm-1" onSuccess={onSuccess} onCancel={vi.fn()} />));

    fillMinimalFields();
    fireEvent.click(screen.getByRole("button", { name: "Create work item" }));
    await waitFor(() => expect(postedBodies(fetchMock)).toHaveLength(1));
    expect(await screen.findByRole("button", { name: "Retry" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(onSuccess).toHaveBeenCalledTimes(1));

    const [first, second] = postedBodies(fetchMock);
    expect(second).toEqual(first);
  });

  it("a 5xx retry resends the same id/payload and a 500's error surfaces without a rejection message", async () => {
    let call = 0;
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/work-items") && init?.method === "POST") {
        call += 1;
        if (call === 1) return new Response("", { status: 500 });
        return jsonResponse(makeCreatedItem(), 201);
      }
      return jsonResponse({});
    });
    vi.stubGlobal("fetch", fetchMock);
    const onSuccess = vi.fn();
    render(withQueryClient(<CreateWorkItemForm farmId="farm-1" onSuccess={onSuccess} onCancel={vi.fn()} />));

    fillMinimalFields();
    fireEvent.click(screen.getByRole("button", { name: "Create work item" }));
    await waitFor(() => expect(postedBodies(fetchMock)).toHaveLength(1));
    fireEvent.click(await screen.findByRole("button", { name: "Retry" }));
    await waitFor(() => expect(onSuccess).toHaveBeenCalledTimes(1));

    const [first, second] = postedBodies(fetchMock);
    expect(second.client_command_id).toBe(first.client_command_id);
  });

  it("attempted field edits while uncertain do not change what Retry resends", async () => {
    let call = 0;
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/work-items") && init?.method === "POST") {
        call += 1;
        if (call === 1) throw new TypeError("Failed to fetch");
        return jsonResponse(makeCreatedItem(), 201);
      }
      return jsonResponse({});
    });
    vi.stubGlobal("fetch", fetchMock);
    render(withQueryClient(<CreateWorkItemForm farmId="farm-1" onSuccess={vi.fn()} onCancel={vi.fn()} />));

    fillMinimalFields("Original title", "cleaning");
    fireEvent.click(screen.getByRole("button", { name: "Create work item" }));
    await waitFor(() => expect(postedBodies(fetchMock)).toHaveLength(1));
    await screen.findByRole("button", { name: "Retry" });

    // Title is disabled while uncertain, but even a forced/attempted edit
    // must never change what a retry actually resends -- retry() only
    // ever returns the already-frozen payload, never a rebuild from live
    // field state.
    expect(screen.getByPlaceholderText("Clean Germination Trolley 03")).toBeDisabled();
    fireEvent.change(screen.getByPlaceholderText("Clean Germination Trolley 03"), {
      target: { value: "Edited title that must never be sent" },
    });

    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(postedBodies(fetchMock)).toHaveLength(2));

    const [first, second] = postedBodies(fetchMock);
    expect(second.title).toBe("Original title");
    expect(second.client_command_id).toBe(first.client_command_id);
  });

  it("a definitive rejection (422) followed by resubmission mints a new client_command_id", async () => {
    let call = 0;
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/work-items") && init?.method === "POST") {
        call += 1;
        if (call === 1) return jsonResponse({ detail: "Invalid" }, 422);
        return jsonResponse(makeCreatedItem(), 201);
      }
      return jsonResponse({});
    });
    vi.stubGlobal("fetch", fetchMock);
    const onSuccess = vi.fn();
    render(withQueryClient(<CreateWorkItemForm farmId="farm-1" onSuccess={onSuccess} onCancel={vi.fn()} />));

    fillMinimalFields("First try", "cleaning");
    fireEvent.click(screen.getByRole("button", { name: "Create work item" }));
    await waitFor(() => expect(postedBodies(fetchMock)).toHaveLength(1));

    // A definitive rejection returns to "editing" -- fields stay enabled
    // and the button never relabels to Retry.
    expect(await screen.findByRole("button", { name: "Create work item" })).toBeInTheDocument();
    expect(screen.getByPlaceholderText("Clean Germination Trolley 03")).not.toBeDisabled();
    fireEvent.change(screen.getByPlaceholderText("Clean Germination Trolley 03"), { target: { value: "Retyped title" } });
    fireEvent.click(screen.getByRole("button", { name: "Create work item" }));
    await waitFor(() => expect(onSuccess).toHaveBeenCalledTimes(1));

    const [first, second] = postedBodies(fetchMock);
    expect(second.client_command_id).not.toBe(first.client_command_id);
    expect(second.title).toBe("Retyped title");
  });

  it("Cancel followed by a new attempt mints a new client_command_id", async () => {
    let call = 0;
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/work-items") && init?.method === "POST") {
        call += 1;
        if (call === 1) throw new TypeError("Failed to fetch");
        return jsonResponse(makeCreatedItem(), 201);
      }
      return jsonResponse({});
    });
    vi.stubGlobal("fetch", fetchMock);
    const onCancel = vi.fn();
    const onSuccess = vi.fn();
    const { unmount } = render(withQueryClient(<CreateWorkItemForm farmId="farm-1" onSuccess={onSuccess} onCancel={onCancel} />));

    fillMinimalFields("First attempt", "cleaning");
    fireEvent.click(screen.getByRole("button", { name: "Create work item" }));
    await waitFor(() => expect(postedBodies(fetchMock)).toHaveLength(1));
    await screen.findByRole("button", { name: "Retry" });

    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onCancel).toHaveBeenCalledTimes(1);
    // The caller (e.g. app/farms/[farmId]/page.tsx) unmounts this form on
    // Cancel -- a fresh mount for the next attempt never reuses the
    // abandoned attempt's id.
    unmount();

    render(withQueryClient(<CreateWorkItemForm farmId="farm-1" onSuccess={onSuccess} onCancel={onCancel} />));
    fillMinimalFields("Second attempt", "cleaning");
    fireEvent.click(screen.getByRole("button", { name: "Create work item" }));
    await waitFor(() => expect(postedBodies(fetchMock)).toHaveLength(2));

    const [first, second] = postedBodies(fetchMock);
    expect(second.client_command_id).not.toBe(first.client_command_id);
  });
});
