import { fireEvent, render, screen, waitFor } from "@testing-library/react";
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

const SAVED = {
  id: "insp-1",
  batch_id: "batch-1",
  overall_assessment: "attention_needed",
  inspected_count: 20,
  effective_time: "2026-09-20T08:00:00Z",
  findings: [],
};

function stubFetch(inspectionResponses: Array<() => Response>) {
  const bodies: Array<Record<string, unknown>> = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.includes("/grower-inspections") && init?.method === "POST") {
        bodies.push(JSON.parse(String(init.body)));
        const next = inspectionResponses.shift();
        return next ? next() : jsonResponse(SAVED);
      }
      if (url.includes("/protocol-status")) return jsonResponse({ protocol: null, due_observation_requirements: [] });
      if (url.includes("/operational-context")) return jsonResponse({ detail: "not found" }, 404);
      if (url.includes("/observation-definitions")) return jsonResponse([]);
      if (url.includes("/crop-batches/batch-1")) return jsonResponse(BATCH);
      return jsonResponse([]);
    }),
  );
  return bodies;
}

afterEach(() => {
  vi.unstubAllGlobals();
  searchParams = new URLSearchParams("batchId=batch-1&assignmentId=bca-1");
});

describe("InspectCropPage (UX-OPS-001C)", () => {
  it("shows context, a summary rail, and one Record Inspection action", async () => {
    stubFetch([]);
    render(withQueryClient(<InspectCropPage />));
    await waitFor(() => expect(screen.getByText(/LET-001 — Lettuce \/ Butterhead/)).toBeInTheDocument());
    expect(screen.getByText("Exact placement (from scan/row)")).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Inspection summary" })).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Record Inspection" })).toHaveLength(1);
  });

  it("retries an uncertain attempt with the same client_command_id and a byte-identical payload, with inputs locked", async () => {
    const bodies = stubFetch([() => jsonResponse({ detail: "upstream" }, 503)]);
    render(withQueryClient(<InspectCropPage />));
    await waitFor(() => expect(screen.getByRole("button", { name: "Record Inspection" })).toBeInTheDocument());

    fireEvent.change(screen.getByLabelText(/inspected count/i), { target: { value: "20" } });
    fireEvent.click(screen.getByRole("button", { name: "Record Inspection" }));

    await waitFor(() => expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument());
    expect(screen.getByRole("alert")).toHaveTextContent(/can never record it twice/i);
    // Locked while uncertain -- what Retry resends can never drift.
    expect(screen.getByLabelText(/inspected count/i)).toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(screen.getByText("Inspection recorded")).toBeInTheDocument());
    expect(bodies).toHaveLength(2);
    expect(bodies[1]).toEqual(bodies[0]);
    expect(bodies[0].batch_carrier_assignment_id).toBe("bca-1");
  });

  it("mints a new client_command_id after a definitive rejection is edited and resubmitted", async () => {
    const bodies = stubFetch([() => jsonResponse({ detail: "affected_count exceeds inspected_count" }, 422)]);
    render(withQueryClient(<InspectCropPage />));
    await waitFor(() => expect(screen.getByRole("button", { name: "Record Inspection" })).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "Record Inspection" }));
    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
    expect(screen.getByLabelText(/inspected count/i)).not.toBeDisabled();

    fireEvent.change(screen.getByLabelText(/inspected count/i), { target: { value: "30" } });
    fireEvent.click(screen.getByRole("button", { name: "Record Inspection" }));
    await waitFor(() => expect(screen.getByText("Inspection recorded")).toBeInTheDocument());
    expect(bodies).toHaveLength(2);
    expect(bodies[1].client_command_id).not.toBe(bodies[0].client_command_id);
  });

  it("shows a truthful receipt from the server response", async () => {
    stubFetch([]);
    render(withQueryClient(<InspectCropPage />));
    await waitFor(() => expect(screen.getByRole("button", { name: "Record Inspection" })).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Record Inspection" }));
    await waitFor(() => expect(screen.getByText("Inspection recorded")).toBeInTheDocument());
    expect(screen.getByText("Attention Needed")).toBeInTheDocument();
    expect(screen.getByText("20")).toBeInTheDocument();
  });
});
