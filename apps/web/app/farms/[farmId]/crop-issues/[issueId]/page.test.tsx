import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { withQueryClient } from "@/lib/test-utils";

import CropIssueWorkspacePage from "./page";

vi.mock("next/navigation", () => ({
  useParams: () => ({ farmId: "farm-1", issueId: "issue-1" }),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/farms/farm-1/crop-issues/issue-1",
  useSearchParams: () => new URLSearchParams(),
}));

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const OPEN_ISSUE = {
  id: "issue-1", tenant_id: "t", farm_id: "farm-1", code: "CI-20260920-0001", batch_id: "batch-1",
  batch_carrier_assignment_id: null, location_id: null, originating_grower_inspection_id: "insp-1",
  originating_finding_id: null, category: "pest_evidence", severity: "medium", description: "Aphids on outer leaves",
  suspected_cause: "Aphids", confirmed_diagnosis: null, diagnosis_confirmed_by_user_id: null,
  diagnosis_confirmed_at: null, status: "open", opened_by_user_id: "u", opened_at: "2026-09-20T08:00:00Z",
  assigned_owner_user_id: null, follow_up_due_at: null, resolved_by_user_id: null, resolved_at: null,
  resolution_note: null, closed_by_user_id: null, closed_at: null, close_note: null,
  updated_at: "2026-09-20T08:00:00Z", has_open_work_item: false, is_follow_up_overdue: false,
};

function stubFetch(issue: Record<string, unknown>, followUpResponses: Array<() => Response> = []) {
  const followUpBodies: Array<Record<string, unknown>> = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.includes("/follow-ups") && init?.method === "POST") {
        followUpBodies.push(JSON.parse(String(init.body)));
        const next = followUpResponses.shift();
        return next ? next() : jsonResponse({ id: "fu-1" });
      }
      if (url.includes("/follow-ups")) return jsonResponse([]);
      if (url.includes("/crop-issues/issue-1")) return jsonResponse(issue);
      if (url.includes("/grower-inspections/")) return jsonResponse({ detail: "nf" }, 404);
      if (url.includes("/crop-batches/batch-1")) return jsonResponse({ id: "batch-1", code: "LET-001" });
      return jsonResponse([]);
    }),
  );
  return followUpBodies;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("CropIssueWorkspacePage (UX-OPS-001C)", () => {
  it("an Open issue offers Resolve as the one primary action, plus Diagnose/Follow-up -- never Close", async () => {
    stubFetch(OPEN_ISSUE);
    render(withQueryClient(<CropIssueWorkspacePage />));
    const rail = await screen.findByRole("region", { name: "Issue status" });
    expect(within(rail).getByRole("button", { name: "Resolve Issue" })).toBeInTheDocument();
    expect(within(rail).getByRole("button", { name: "Confirm Diagnosis" })).toBeInTheDocument();
    expect(within(rail).getByRole("button", { name: "Add Follow-up" })).toBeInTheDocument();
    expect(within(rail).queryByRole("button", { name: /close issue/i })).not.toBeInTheDocument();
    // Suspected cause and confirmed diagnosis stay distinct.
    expect(screen.getByText("Aphids")).toBeInTheDocument();
    expect(screen.getByText("Not confirmed")).toBeInTheDocument();
  });

  it("a Resolved issue offers only Close; a Closed issue offers no action", async () => {
    stubFetch({ ...OPEN_ISSUE, status: "resolved", resolved_at: "2026-09-21T08:00:00Z", resolution_note: "Sprayed" });
    const { unmount } = render(withQueryClient(<CropIssueWorkspacePage />));
    const rail = await screen.findByRole("region", { name: "Issue status" });
    expect(within(rail).getByRole("button", { name: "Close Issue" })).toBeInTheDocument();
    expect(within(rail).queryByRole("button", { name: /resolve issue/i })).not.toBeInTheDocument();
    expect(within(rail).queryByRole("button", { name: "Add Follow-up" })).not.toBeInTheDocument();
    unmount();

    stubFetch({ ...OPEN_ISSUE, status: "closed", closed_at: "2026-09-22T08:00:00Z" });
    render(withQueryClient(<CropIssueWorkspacePage />));
    const closedRail = await screen.findByRole("region", { name: "Issue status" });
    expect(within(closedRail).queryAllByRole("button")).toHaveLength(0);
  });

  it("retries an uncertain follow-up with the same client_command_id instead of recording a duplicate", async () => {
    const bodies = stubFetch(OPEN_ISSUE, [() => jsonResponse({ detail: "upstream" }, 503)]);
    render(withQueryClient(<CropIssueWorkspacePage />));
    const rail = await screen.findByRole("region", { name: "Issue status" });
    fireEvent.click(within(rail).getByRole("button", { name: "Add Follow-up" }));
    fireEvent.change(within(rail).getByLabelText(/notes/i), { target: { value: "Fewer aphids" } });
    fireEvent.click(within(rail).getByRole("button", { name: "Save Follow-up" }));

    await waitFor(() => expect(within(rail).getByRole("button", { name: "Retry" })).toBeInTheDocument());
    expect(within(rail).getByLabelText(/notes/i)).toBeDisabled();
    // UX-OPS-001C/R1: an unresolved attempt can never be cancelled/abandoned.
    expect(within(rail).getByRole("button", { name: "Cancel" })).toBeDisabled();
    fireEvent.click(within(rail).getByRole("button", { name: "Cancel" }));
    expect(within(rail).getByRole("button", { name: "Retry" })).toBeInTheDocument();
    fireEvent.click(within(rail).getByRole("button", { name: "Retry" }));

    await waitFor(() => expect(bodies).toHaveLength(2));
    expect(bodies[1]).toEqual(bodies[0]);
    await waitFor(() => expect(within(rail).queryByRole("button", { name: "Retry" })).not.toBeInTheDocument());
  });

  it("UX-OPS-001C/R1: a definitive rejection releases the attempt (Cancel re-enabled) and the next save mints a new id", async () => {
    const bodies = stubFetch(OPEN_ISSUE, [() => jsonResponse({ detail: "invalid" }, 422)]);
    render(withQueryClient(<CropIssueWorkspacePage />));
    const rail = await screen.findByRole("region", { name: "Issue status" });
    fireEvent.click(within(rail).getByRole("button", { name: "Add Follow-up" }));
    fireEvent.click(within(rail).getByRole("button", { name: "Save Follow-up" }));
    await waitFor(() => expect(within(rail).getByRole("button", { name: "Cancel" })).toBeEnabled());
    expect(within(rail).getByRole("button", { name: "Save Follow-up" })).toBeInTheDocument();
    fireEvent.click(within(rail).getByRole("button", { name: "Save Follow-up" }));
    await waitFor(() => expect(bodies).toHaveLength(2));
    expect(bodies[1].client_command_id).not.toBe(bodies[0].client_command_id);
  });
});
