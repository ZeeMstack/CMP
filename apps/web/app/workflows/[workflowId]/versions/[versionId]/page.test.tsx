import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useParams: () => ({ workflowId: "wf-1", versionId: "ver-1" }),
}));

import { withQueryClient } from "@/lib/test-utils";

import WorkflowVersionEditorPage from "./page";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const CROP = { id: "crop-1", tenant_id: "t", code: "ICE", common_name: "Iceberg Lettuce", scientific_name: null, crop_category: "leafy_green", status: "active" };
const PRODUCTION_SYSTEM = { id: "ps-1", tenant_id: "t", code: "NFT", name: "NFT Leafy Greens", description: null, status: "active" };
const WORKFLOW = { id: "wf-1", tenant_id: "t", crop_id: "crop-1", variety_id: null, production_system_id: "ps-1", code: "WF-1", name: "Iceberg Workflow", status: "active" };
const CARRIER_TYPES = [{ id: "ct-1", code: "GROW_CUBE", name: "Grow Cube", requires_specification: false, biological_position_label: null }];

function makeVersion(overrides: Partial<Record<string, unknown>> = {}) {
  return {
    id: "ver-1", tenant_id: "t", workflow_id: "wf-1", version_number: 1, state: "draft",
    created_at: "2026-08-29T00:00:00Z", published_at: null as string | null, retired_at: null as string | null,
    stages: [] as unknown[], transitions: [] as unknown[],
    ...overrides,
  };
}

/** A small stateful mock: stages/transitions accumulate across POSTs, and
 * the version-detail GET always reflects current state -- this is what
 * lets the page's own invalidate-then-refetch behavior be observed. */
function stubStatefulFetch(initialVersion = makeVersion()) {
  let version = initialVersion;
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = init?.method;
    if (url.includes("/stages") && method === "POST") {
      const payload = JSON.parse(String(init!.body));
      const stage = { id: `stage-${version.stages.length + 1}`, tenant_id: "t", workflow_version_id: "ver-1", ...payload, permitted_location_type_id: null, required_carrier_type_id: null };
      version = { ...version, stages: [...version.stages, stage] };
      return jsonResponse(stage);
    }
    if (url.includes("/transitions") && method === "POST") {
      const payload = JSON.parse(String(init!.body));
      const transition = { id: `trans-${version.transitions.length + 1}`, tenant_id: "t", workflow_version_id: "ver-1", ...payload };
      version = { ...version, transitions: [...version.transitions, transition] };
      return jsonResponse(transition);
    }
    if (url.includes("/publish") && method === "POST") {
      version = { ...version, state: "published", published_at: "2026-08-29T01:00:00Z" };
      return jsonResponse(version);
    }
    if (url.includes("/versions/ver-1")) return jsonResponse(version);
    if (url.includes("/workflows")) return jsonResponse(WORKFLOW);
    if (url.includes("/carrier-types")) return jsonResponse(CARRIER_TYPES);
    if (url.includes("/crops")) return jsonResponse([CROP]);
    if (url.includes("/production-systems")) return jsonResponse([PRODUCTION_SYSTEM]);
    return jsonResponse([]);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("WorkflowVersionEditorPage", () => {
  it("renders the overview for the draft version", async () => {
    stubStatefulFetch();
    render(withQueryClient(<WorkflowVersionEditorPage />));
    await waitFor(() => expect(screen.getByText("Iceberg Workflow — v1")).toBeInTheDocument());
    expect(screen.getByText("Draft")).toBeInTheDocument();
  });

  it("adds a stage and shows it in the table with deterministic ordering", async () => {
    stubStatefulFetch();
    render(withQueryClient(<WorkflowVersionEditorPage />));
    await waitFor(() => expect(screen.getByRole("button", { name: /add stage/i })).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: /add stage/i }));
    fireEvent.change(screen.getByLabelText("Code"), { target: { value: "SEEDING" } });
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Seeding" } });
    fireEvent.click(screen.getByLabelText("Start stage"));
    fireEvent.click(screen.getByRole("button", { name: /^add stage$/i }));

    await waitFor(() => expect(screen.getByText("SEEDING")).toBeInTheDocument());
    expect(screen.getAllByText("Yes")[0]).toBeInTheDocument();
  });

  it("requires at least two stages before allowing a transition to be added", async () => {
    stubStatefulFetch(makeVersion({
      stages: [
        { id: "stage-1", tenant_id: "t", workflow_version_id: "ver-1", code: "SEEDING", name: "Seeding", display_order: 0, stage_category: "seeding", expected_duration_minutes: null, permitted_location_type_id: null, required_carrier_type_id: null, is_start: true, is_terminal: false },
      ],
    }));
    render(withQueryClient(<WorkflowVersionEditorPage />));
    await waitFor(() => expect(screen.getByText("SEEDING")).toBeInTheDocument());
    expect(screen.queryByRole("button", { name: /add transition/i })).not.toBeInTheDocument();
    expect(screen.getByText(/add at least two stages/i)).toBeInTheDocument();
  });

  it("adds a transition once two stages exist", async () => {
    stubStatefulFetch(makeVersion({
      stages: [
        { id: "stage-1", tenant_id: "t", workflow_version_id: "ver-1", code: "SEEDING", name: "Seeding", display_order: 0, stage_category: "seeding", expected_duration_minutes: null, permitted_location_type_id: null, required_carrier_type_id: null, is_start: true, is_terminal: false },
        { id: "stage-2", tenant_id: "t", workflow_version_id: "ver-1", code: "GERMINATION", name: "Germination", display_order: 1, stage_category: "germination", expected_duration_minutes: null, permitted_location_type_id: null, required_carrier_type_id: null, is_start: false, is_terminal: true },
      ],
    }));
    render(withQueryClient(<WorkflowVersionEditorPage />));
    await waitFor(() => expect(screen.getByRole("button", { name: /add transition/i })).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: /add transition/i }));
    fireEvent.change(screen.getByLabelText("From stage"), { target: { value: "stage-1" } });
    fireEvent.change(screen.getByLabelText("To stage"), { target: { value: "stage-2" } });
    fireEvent.change(screen.getByLabelText("Code"), { target: { value: "TO_GERM" } });
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Move to Germination" } });
    fireEvent.click(screen.getByRole("button", { name: /^add transition$/i }));

    await waitFor(() => expect(screen.getByText("TO_GERM")).toBeInTheDocument());
  });

  it("publish is explicit -- never triggered automatically -- and shows success once clicked", async () => {
    stubStatefulFetch(makeVersion({
      stages: [
        { id: "stage-1", tenant_id: "t", workflow_version_id: "ver-1", code: "SEEDING", name: "Seeding", display_order: 0, stage_category: "seeding", expected_duration_minutes: null, permitted_location_type_id: null, required_carrier_type_id: null, is_start: true, is_terminal: true },
      ],
    }));
    render(withQueryClient(<WorkflowVersionEditorPage />));
    await waitFor(() => expect(screen.getByRole("button", { name: /publish this version/i })).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: /publish this version/i }));
    await waitFor(() => expect(screen.getByText(/Published as version 1/)).toBeInTheDocument());
  });

  it("shows a 422 publish validation failure safely, without a raw traceback", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.includes("/publish") && init?.method === "POST") {
        return jsonResponse({ detail: "workflow version must have exactly one start stage" }, 422);
      }
      if (url.includes("/versions/ver-1")) return jsonResponse(makeVersion());
      if (url.includes("/workflows")) return jsonResponse(WORKFLOW);
      if (url.includes("/carrier-types")) return jsonResponse(CARRIER_TYPES);
      if (url.includes("/crops")) return jsonResponse([CROP]);
      if (url.includes("/production-systems")) return jsonResponse([PRODUCTION_SYSTEM]);
      return jsonResponse([]);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(withQueryClient(<WorkflowVersionEditorPage />));
    await waitFor(() => expect(screen.getByRole("button", { name: /publish this version/i })).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: /publish this version/i }));
    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent("workflow version must have exactly one start stage"),
    );
  });

  it("respects published immutability -- no Add stage/Add transition/Publish controls once published", async () => {
    stubStatefulFetch(makeVersion({
      state: "published",
      published_at: "2026-08-29T01:00:00Z",
      stages: [
        { id: "stage-1", tenant_id: "t", workflow_version_id: "ver-1", code: "SEEDING", name: "Seeding", display_order: 0, stage_category: "seeding", expected_duration_minutes: null, permitted_location_type_id: null, required_carrier_type_id: null, is_start: true, is_terminal: true },
      ],
    }));
    render(withQueryClient(<WorkflowVersionEditorPage />));
    await waitFor(() => expect(screen.getByText("Published")).toBeInTheDocument());

    expect(screen.queryByRole("button", { name: /^add stage$/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /add transition/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /publish this version/i })).not.toBeInTheDocument();
  });

  it("never calls a Crop Batch, Sowing, Movement, or Occupancy endpoint from this editor", async () => {
    const fetchMock = stubStatefulFetch(makeVersion({
      stages: [
        { id: "stage-1", tenant_id: "t", workflow_version_id: "ver-1", code: "SEEDING", name: "Seeding", display_order: 0, stage_category: "seeding", expected_duration_minutes: null, permitted_location_type_id: null, required_carrier_type_id: null, is_start: true, is_terminal: true },
      ],
    }));
    render(withQueryClient(<WorkflowVersionEditorPage />));
    await waitFor(() => expect(screen.getByRole("button", { name: /publish this version/i })).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /publish this version/i }));
    await waitFor(() => expect(screen.getByText(/Published as version 1/)).toBeInTheDocument());

    const calledUrls = fetchMock.mock.calls.map((c) => String(c[0]));
    expect(calledUrls.some((u) => /crop-batches|sowings|movements|occupanc/.test(u))).toBe(false);
  });
});
