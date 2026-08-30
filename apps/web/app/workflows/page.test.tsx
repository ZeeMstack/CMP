import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { withQueryClient } from "@/lib/test-utils";

import WorkflowsPage from "./page";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const CROP = { id: "crop-1", tenant_id: "t", code: "ICE", common_name: "Iceberg Lettuce", scientific_name: null, crop_category: "leafy_green", status: "active" };
const PRODUCTION_SYSTEM = { id: "ps-1", tenant_id: "t", code: "NFT", name: "NFT Leafy Greens", description: null, status: "active" };
const WORKFLOW = {
  id: "wf-1", tenant_id: "t", crop_id: "crop-1", variety_id: null, production_system_id: "ps-1",
  code: "WF-1", name: "Iceberg Workflow", status: "active",
};

function stubFetch(workflows: unknown[]) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/workflows")) return jsonResponse(workflows);
      if (url.includes("/crops")) return jsonResponse([CROP]);
      if (url.includes("/production-systems")) return jsonResponse([PRODUCTION_SYSTEM]);
      return jsonResponse([]);
    }),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("WorkflowsPage", () => {
  it("renders each workflow joined against its Crop and Production System names", async () => {
    stubFetch([WORKFLOW]);
    render(withQueryClient(<WorkflowsPage />));
    await waitFor(() => expect(screen.getByText("WF-1")).toBeInTheDocument());
    expect(screen.getByText("Iceberg Lettuce")).toBeInTheDocument();
    expect(screen.getByText("NFT Leafy Greens")).toBeInTheDocument();
  });

  it("shows empty state with no workflows", async () => {
    stubFetch([]);
    render(withQueryClient(<WorkflowsPage />));
    await waitFor(() => expect(screen.getByText("No workflows yet")).toBeInTheDocument());
  });

  it("links New Workflow to the creation route, never publishing anything on this list page", async () => {
    stubFetch([]);
    render(withQueryClient(<WorkflowsPage />));
    await waitFor(() => expect(screen.getByText("No workflows yet")).toBeInTheDocument());
    expect(screen.getByRole("link", { name: /new workflow/i })).toHaveAttribute("href", "/workflows/new");
    expect(screen.queryByRole("button", { name: /publish/i })).not.toBeInTheDocument();
  });

  it("View links to this workflow's own shell page", async () => {
    stubFetch([WORKFLOW]);
    render(withQueryClient(<WorkflowsPage />));
    await waitFor(() => expect(screen.getByText("WF-1")).toBeInTheDocument());
    expect(screen.getByRole("link", { name: "View" })).toHaveAttribute("href", "/workflows/wf-1");
  });
});
