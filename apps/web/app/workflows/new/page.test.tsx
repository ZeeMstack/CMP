import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const pushMock = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock }),
}));

import { withQueryClient } from "@/lib/test-utils";

import NewWorkflowPage from "./page";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const CROP = { id: "crop-1", tenant_id: "t", code: "ICE", common_name: "Iceberg Lettuce", scientific_name: null, crop_category: "leafy_green", status: "active" };
const PRODUCTION_SYSTEM = { id: "ps-1", tenant_id: "t", code: "NFT", name: "NFT Leafy Greens", description: null, status: "active" };
const NEW_WORKFLOW = { id: "wf-1", tenant_id: "t", crop_id: "crop-1", variety_id: null, production_system_id: "ps-1", code: "WF-1", name: "Workflow 1", status: "active" };
const NEW_VERSION = { id: "ver-1", tenant_id: "t", workflow_id: "wf-1", version_number: 1, state: "draft", created_at: "2026-08-29T00:00:00Z", published_at: null, retired_at: null };

function stubFetch(overrides: { workflowPost?: unknown; versionPost?: unknown } = {}) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.includes("/versions") && init?.method === "POST") {
        return overrides.versionPost ?? jsonResponse(NEW_VERSION);
      }
      if (url.includes("/workflows") && init?.method === "POST") {
        return overrides.workflowPost ?? jsonResponse(NEW_WORKFLOW);
      }
      if (url.includes("/crops")) return jsonResponse([CROP]);
      if (url.includes("/production-systems")) return jsonResponse([PRODUCTION_SYSTEM]);
      return jsonResponse([]);
    }),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
  pushMock.mockClear();
});

describe("NewWorkflowPage", () => {
  it("creates the workflow, then its first draft version, then navigates to the version editor", async () => {
    stubFetch();
    render(withQueryClient(<NewWorkflowPage />));
    await waitFor(() => expect(screen.getByLabelText("Crop")).toBeInTheDocument());

    fireEvent.change(screen.getByLabelText("Code"), { target: { value: "wf-1" } });
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Workflow 1" } });
    fireEvent.change(screen.getByLabelText("Crop"), { target: { value: "crop-1" } });
    fireEvent.change(screen.getByLabelText("Production system"), { target: { value: "ps-1" } });
    fireEvent.click(screen.getByRole("button", { name: /create workflow draft/i }));

    await waitFor(() => expect(pushMock).toHaveBeenCalledWith("/workflows/wf-1/versions/ver-1"));
  });

  it("still routes to the workflow's own shell page if the automatic draft-version creation fails", async () => {
    stubFetch({ versionPost: jsonResponse({ detail: "server error" }, 500) });
    render(withQueryClient(<NewWorkflowPage />));
    await waitFor(() => expect(screen.getByLabelText("Crop")).toBeInTheDocument());

    fireEvent.change(screen.getByLabelText("Code"), { target: { value: "wf-1" } });
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Workflow 1" } });
    fireEvent.change(screen.getByLabelText("Crop"), { target: { value: "crop-1" } });
    fireEvent.change(screen.getByLabelText("Production system"), { target: { value: "ps-1" } });
    fireEvent.click(screen.getByRole("button", { name: /create workflow draft/i }));

    await waitFor(() => expect(pushMock).toHaveBeenCalledWith("/workflows/wf-1"));
  });

  it("requires at least one crop and one production system before allowing creation", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse([])));
    render(withQueryClient(<NewWorkflowPage />));
    await waitFor(() => expect(screen.getByText(/register at least one crop/i)).toBeInTheDocument());
  });

  it("never calls a Crop Batch, Sowing, or Seed Lot endpoint from this flow", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.includes("/versions") && init?.method === "POST") return jsonResponse(NEW_VERSION);
      if (url.includes("/workflows") && init?.method === "POST") return jsonResponse(NEW_WORKFLOW);
      if (url.includes("/crops")) return jsonResponse([CROP]);
      if (url.includes("/production-systems")) return jsonResponse([PRODUCTION_SYSTEM]);
      return jsonResponse([]);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(withQueryClient(<NewWorkflowPage />));
    await waitFor(() => expect(screen.getByLabelText("Crop")).toBeInTheDocument());

    fireEvent.change(screen.getByLabelText("Code"), { target: { value: "wf-1" } });
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Workflow 1" } });
    fireEvent.change(screen.getByLabelText("Crop"), { target: { value: "crop-1" } });
    fireEvent.change(screen.getByLabelText("Production system"), { target: { value: "ps-1" } });
    fireEvent.click(screen.getByRole("button", { name: /create workflow draft/i }));

    await waitFor(() => expect(pushMock).toHaveBeenCalled());
    const calledUrls = fetchMock.mock.calls.map((c) => String(c[0]));
    expect(calledUrls.some((u) => /crop-batches|sowings|seed-lots/.test(u))).toBe(false);
  });
});
