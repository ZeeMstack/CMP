import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { withQueryClient } from "@/lib/test-utils";

import InspectCropPage from "./page";

let searchParams = new URLSearchParams("batchId=batch-1&assignmentId=bca-1");
const push = vi.fn();

vi.mock("next/navigation", () => ({
  useParams: () => ({ farmId: "farm-1" }),
  useSearchParams: () => searchParams,
  useRouter: () => ({ push }),
}));

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const BATCH = {
  id: "batch-1",
  code: "LET-001",
  crop: { id: "crop-1", code: "LET", common_name: "Lettuce" },
  variety: { id: "var-1", code: "BUT", name: "Butterhead" },
  current_stage: { id: "stage-1", code: "grow", name: "Grow-out" },
};

const carrierType = { id: "ct", code: "production_cultivation_plate", name: "Plate" };
const TARGETS = [
  { id: "bca-1", carrier: { id: "c1", code: "PP-001", carrier_type: carrierType }, location_label: "LEAFY-01 / Z01 / S01 / TA01" },
  { id: "bca-2", carrier: { id: "c2", code: "PP-002", carrier_type: carrierType }, location_label: "LEAFY-01 / Z01 / S02 / TA07" },
];

const DEFINITIONS = [
  {
    id: "def-h", code: "HEIGHT", name: "Plant height", description: null, value_type: "decimal", unit: "cm",
    target_scope: "either", min_value: null, max_value: null, status: "active",
  },
];

const STATUS = {
  protocol: { id: "p", name: "Lettuce GP" },
  protocol_version: { id: "pv", version_number: 2 },
  due_observation_requirements: [
    {
      requirement: { id: "req-1", observation_definition_id: "def-h", requirement_level: "required" },
      observation_definition_name: "Plant height", is_due: true, is_overdue: false,
    },
  ],
};

function saved(body: Record<string, unknown>) {
  return {
    id: "insp-1", batch_id: "batch-1", batch_carrier_assignment_id: body.batch_carrier_assignment_id,
    location_id: "loc-ta01", overall_assessment: body.overall_assessment, inspected_count: body.inspected_count,
    effective_time: "2026-09-20T08:00:00Z", observation_event_id: "obs-1",
    findings: ((body.findings as unknown[]) ?? []).map((f, i) => ({ id: `f-${i}`, ...(f as object) })),
  };
}

function stubFetch(inspectionResponses: Array<(body: Record<string, unknown>) => Response> = []) {
  const bodies: Array<Record<string, unknown>> = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.includes("/grower-inspections") && init?.method === "POST") {
        const body = JSON.parse(String(init.body));
        bodies.push(body);
        const next = inspectionResponses.shift();
        return next ? next(body) : jsonResponse(saved(body));
      }
      if (url.includes("/observation-targets")) return jsonResponse(TARGETS);
      if (url.includes("/protocol-status")) return jsonResponse(STATUS);
      if (url.includes("/observation-definitions")) return jsonResponse(DEFINITIONS);
      if (url.includes("/locations/loc-ta01/path")) {
        return jsonResponse({ location_id: "loc-ta01", path: [], path_string: "LEAFY-01 / Z01 / S01 / TA01" });
      }
      if (url.includes("/observations")) {
        return jsonResponse([{ id: "obs-1", values: [{ id: "v1" }], germination_checks: [] }]);
      }
      if (url.includes("/crop-batches/batch-1")) return jsonResponse(BATCH);
      return jsonResponse([]);
    }),
  );
  return bodies;
}

async function fillAndReview() {
  await waitFor(() => expect(screen.getByLabelText(/plant height/i)).toBeInTheDocument());
  fireEvent.change(screen.getByLabelText(/inspected count/i), { target: { value: "20" } });
  fireEvent.change(screen.getByLabelText(/plant height/i), { target: { value: "14.5" } });
  fireEvent.click(screen.getByRole("button", { name: "Review Inspection" }));
  await waitFor(() => expect(screen.getByText("Review before recording")).toBeInTheDocument());
}

afterEach(() => {
  vi.unstubAllGlobals();
  searchParams = new URLSearchParams("batchId=batch-1&assignmentId=bca-1");
});

describe("InspectCropPage (UX-OPS-001C/R1)", () => {
  it("shows the resolved carrier/location and submits exactly that assignment (inspection + observation values)", async () => {
    const bodies = stubFetch();
    render(withQueryClient(<InspectCropPage />));
    await waitFor(() => expect(screen.getByTestId("inspection-target")).toHaveTextContent("PP-001 — LEAFY-01 / Z01 / S01 / TA01"));

    await fillAndReview();
    // Review restates the exact target and every entered value.
    expect(screen.getAllByText("PP-001").length).toBeGreaterThan(0);
    expect(screen.getByText("14.5 cm")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Record Inspection" }));

    await waitFor(() => expect(screen.getByText("Inspection recorded")).toBeInTheDocument());
    expect(bodies).toHaveLength(1);
    expect(bodies[0].batch_carrier_assignment_id).toBe("bca-1");
    expect(bodies[0].observation_values).toEqual([
      expect.objectContaining({ observation_definition_id: "def-h", batch_carrier_assignment_id: "bca-1", value_decimal: 14.5 }),
    ]);
  });

  it("blocks a missing/foreign assignment and never labels it as an exact placement", async () => {
    searchParams = new URLSearchParams("batchId=batch-1&assignmentId=bca-OTHER-BATCH");
    const bodies = stubFetch();
    render(withQueryClient(<InspectCropPage />));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(/not an active placement of this Batch/i));
    expect(screen.getByRole("button", { name: "Review Inspection" })).toBeDisabled();
    expect(screen.queryByTestId("inspection-target")).not.toBeInTheDocument();
    expect(bodies).toHaveLength(0);
  });

  it("opened without an assignment, requires choosing an exact placement; changing it clears the draft", async () => {
    searchParams = new URLSearchParams("batchId=batch-1");
    stubFetch();
    render(withQueryClient(<InspectCropPage />));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(/choose the exact placement/i));
    expect(screen.getByRole("button", { name: "Review Inspection" })).toBeDisabled();

    const picker = screen.getByLabelText(/exact placement being inspected/i);
    await waitFor(() => expect(within(picker).getByText(/PP-002/)).toBeInTheDocument());
    fireEvent.change(picker, { target: { value: "bca-1" } });
    await waitFor(() => expect(screen.getByTestId("inspection-target")).toHaveTextContent("PP-001"));
    fireEvent.change(screen.getByLabelText(/inspected count/i), { target: { value: "20" } });

    fireEvent.change(picker, { target: { value: "bca-2" } });
    await waitFor(() => expect(screen.getByTestId("inspection-target")).toHaveTextContent("PP-002 — LEAFY-01 / Z01 / S02 / TA07"));
    expect(screen.getByLabelText(/inspected count/i)).toHaveValue("");
  });

  it("Review/Back never mints an id; the payload is frozen only on Record", async () => {
    const bodies = stubFetch();
    render(withQueryClient(<InspectCropPage />));
    await fillAndReview();
    fireEvent.click(screen.getByRole("button", { name: "Back to edit" }));
    fireEvent.click(screen.getByRole("button", { name: "Review Inspection" }));
    await waitFor(() => expect(screen.getByText("Review before recording")).toBeInTheDocument());
    expect(bodies).toHaveLength(0);
    fireEvent.click(screen.getByRole("button", { name: "Record Inspection" }));
    await waitFor(() => expect(bodies).toHaveLength(1));
  });

  it("an uncertain attempt locks Back (no discard) and Retry resends the byte-identical payload", async () => {
    const bodies = stubFetch([() => jsonResponse({ detail: "upstream" }, 503)]);
    render(withQueryClient(<InspectCropPage />));
    await fillAndReview();
    fireEvent.click(screen.getByRole("button", { name: "Record Inspection" }));

    await waitFor(() => expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument());
    expect(screen.getByRole("alert")).toHaveTextContent(/can never apply it twice/i);
    expect(screen.getByRole("button", { name: "Back to edit" })).toBeDisabled();
    expect(screen.queryByRole("button", { name: /discard/i })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(screen.getByText("Inspection recorded")).toBeInTheDocument());
    expect(bodies).toHaveLength(2);
    expect(JSON.stringify(bodies[1])).toBe(JSON.stringify(bodies[0]));
  });

  it("a definitive rejection unlocks editing and the resubmission gets a new client_command_id", async () => {
    const bodies = stubFetch([() => jsonResponse({ detail: "effective_time precedes batch" }, 422)]);
    render(withQueryClient(<InspectCropPage />));
    await fillAndReview();
    fireEvent.click(screen.getByRole("button", { name: "Record Inspection" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Back to edit" })).toBeEnabled());
    expect(screen.getByRole("button", { name: "Record Inspection" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Back to edit" }));
    fireEvent.change(screen.getByLabelText(/inspected count/i), { target: { value: "30" } });
    fireEvent.click(screen.getByRole("button", { name: "Review Inspection" }));
    await waitFor(() => expect(screen.getByText("Review before recording")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Record Inspection" }));
    await waitFor(() => expect(screen.getByText("Inspection recorded")).toBeInTheDocument());
    expect(bodies).toHaveLength(2);
    expect(bodies[1].client_command_id).not.toBe(bodies[0].client_command_id);
  });

  it("renders the receipt from the server response: carrier, stored location snapshot, counts; keeps next actions", async () => {
    stubFetch();
    render(withQueryClient(<InspectCropPage />));
    await fillAndReview();
    fireEvent.click(screen.getByRole("button", { name: "Back to edit" }));
    fireEvent.click(screen.getByRole("button", { name: "+ Add finding" }));
    fireEvent.click(screen.getByRole("button", { name: "Review Inspection" }));
    await waitFor(() => expect(screen.getByText("Review before recording")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Record Inspection" }));

    await waitFor(() => expect(screen.getByText("Inspection recorded")).toBeInTheDocument());
    const receipt = screen.getByRole("status");
    expect(within(receipt).getByText("LET-001")).toBeInTheDocument();
    expect(within(receipt).getByText("PP-001")).toBeInTheDocument();
    await waitFor(() => expect(within(receipt).getByText("LEAFY-01 / Z01 / S01 / TA01")).toBeInTheDocument());
    expect(within(receipt).getByText("Normal")).toBeInTheDocument();
    expect(within(receipt).getByText("Inspected").nextElementSibling).toHaveTextContent("20");
    // Observation count is read back from the recorded ObservationEvent.
    await waitFor(() => expect(within(receipt).getByText("Observations").nextElementSibling).toHaveTextContent("1"));
    expect(within(receipt).getByText("Findings").nextElementSibling).toHaveTextContent("1");
    for (const name of ["Done", "Record another inspection", "Open Crop Issue"]) {
      expect(within(receipt).getByRole("button", { name })).toBeInTheDocument();
    }
    expect(within(receipt).getByRole("link", { name: "View Batch" })).toBeInTheDocument();
  });

  it("an uncertain Open Crop Issue cannot be cancelled and retries byte-identically", async () => {
    stubFetch();
    const issueBodies: string[] = [];
    let issueCalls = 0;
    const baseFetch = globalThis.fetch;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        if (String(input).endsWith("/crop-issues") && init?.method === "POST") {
          issueBodies.push(String(init.body));
          issueCalls += 1;
          return issueCalls === 1 ? jsonResponse({ detail: "x" }, 502) : jsonResponse({ id: "issue-9" });
        }
        return baseFetch(input, init);
      }),
    );
    render(withQueryClient(<InspectCropPage />));
    await waitFor(() => expect(screen.getByRole("button", { name: "+ Add finding" })).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "+ Add finding" }));
    fireEvent.click(screen.getByRole("button", { name: "Review Inspection" }));
    await waitFor(() => expect(screen.getByText("Review before recording")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Record Inspection" }));
    await waitFor(() => expect(screen.getByText("Inspection recorded")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "Open Crop Issue" }));
    fireEvent.change(screen.getByLabelText("Description"), { target: { value: "Tip burn spreading" } });
    fireEvent.click(screen.getByRole("button", { name: "Open Issue" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Cancel" })).toBeDisabled();
    expect(screen.getByLabelText("Description")).toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(push).toHaveBeenCalledWith("/farms/farm-1/crop-issues/issue-9"));
    expect(issueBodies[1]).toBe(issueBodies[0]);
  });
});
