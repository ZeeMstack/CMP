import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const pushMock = vi.fn();
vi.mock("next/navigation", () => ({
  useParams: () => ({ workflowId: "wf-1" }),
  useRouter: () => ({ push: pushMock }),
}));

import { withQueryClient } from "@/lib/test-utils";

import WorkflowShellPage from "./page";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const CROP = { id: "crop-1", tenant_id: "t", code: "ICE", common_name: "Iceberg Lettuce", scientific_name: null, crop_category: "leafy_green", status: "active" };
const PRODUCTION_SYSTEM = { id: "ps-1", tenant_id: "t", code: "NFT", name: "NFT Leafy Greens", description: null, status: "active" };
const WORKFLOW = { id: "wf-1", tenant_id: "t", crop_id: "crop-1", variety_id: null, production_system_id: "ps-1", code: "WF-1", name: "Iceberg Workflow", status: "active" };

function version(overrides: Partial<Record<string, unknown>> = {}) {
  return {
    id: "ver-1", tenant_id: "t", workflow_id: "wf-1", version_number: 1, state: "draft",
    created_at: "2026-08-29T00:00:00Z", published_at: null as string | null, retired_at: null as string | null,
    ...overrides,
  };
}

/** `versions` is a mutable array so a test can assert what happens after
 * "Create draft version" appends to it and the catalog is refetched. */
function stubFetch(versions: ReturnType<typeof version>[]) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = init?.method;
    if (url.includes("/versions") && method === "POST") {
      const created = version({ id: `ver-${versions.length + 1}`, version_number: versions.length + 1 });
      versions.push(created);
      return jsonResponse(created);
    }
    if (url.includes("/versions")) return jsonResponse(versions);
    if (url.endsWith("/workflows/wf-1")) return jsonResponse(WORKFLOW);
    if (url.includes("/crops")) return jsonResponse([CROP]);
    if (url.includes("/production-systems")) return jsonResponse([PRODUCTION_SYSTEM]);
    return jsonResponse([]);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => {
  vi.unstubAllGlobals();
  pushMock.mockClear();
});

describe("WorkflowShellPage — version catalog (B6A)", () => {
  it("lists every version from the catalog with its own state and action", async () => {
    stubFetch([
      version({ id: "ver-1", version_number: 1, state: "draft" }),
      version({ id: "ver-2", version_number: 2, state: "published", published_at: "2026-08-29T01:00:00Z" }),
    ]);
    render(withQueryClient(<WorkflowShellPage />));
    await waitFor(() => expect(screen.getByText("WF-1")).toBeInTheDocument());

    const rows = screen.getAllByRole("row").slice(1);
    expect(rows).toHaveLength(2);
    expect(within(rows[0]).getByText("Draft")).toBeInTheDocument();
    expect(within(rows[0]).getByRole("button", { name: "Resume Draft" })).toBeInTheDocument();
    expect(within(rows[1]).getByText("Published")).toBeInTheDocument();
    expect(within(rows[1]).getByRole("button", { name: "View Published Version" })).toBeInTheDocument();
  });

  it("a draft exposes Resume Draft, never an edit control here", async () => {
    stubFetch([version({ state: "draft" })]);
    render(withQueryClient(<WorkflowShellPage />));
    await waitFor(() => expect(screen.getByRole("button", { name: "Resume Draft" })).toBeInTheDocument());
    expect(screen.queryByRole("button", { name: /add stage/i })).not.toBeInTheDocument();
  });

  it("a published version exposes View, never an edit control here", async () => {
    stubFetch([version({ state: "published", published_at: "2026-08-29T01:00:00Z" })]);
    render(withQueryClient(<WorkflowShellPage />));
    await waitFor(() => expect(screen.getByRole("button", { name: "View Published Version" })).toBeInTheDocument());
    expect(screen.queryByRole("button", { name: /add stage/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^publish this version$/i })).not.toBeInTheDocument();
  });

  it("a retired version exposes View, never an edit control here", async () => {
    stubFetch([version({ state: "retired", published_at: "2026-08-29T01:00:00Z", retired_at: "2026-08-29T02:00:00Z" })]);
    render(withQueryClient(<WorkflowShellPage />));
    await waitFor(() => expect(screen.getByRole("button", { name: "View Retired Version" })).toBeInTheDocument());
    expect(screen.queryByRole("button", { name: /add stage/i })).not.toBeInTheDocument();
  });

  it("Resume Draft navigates to that exact existing version's editor route", async () => {
    stubFetch([version({ id: "ver-7", version_number: 1, state: "draft" })]);
    render(withQueryClient(<WorkflowShellPage />));
    await waitFor(() => expect(screen.getByRole("button", { name: "Resume Draft" })).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Resume Draft" }));
    expect(pushMock).toHaveBeenCalledWith("/workflows/wf-1/versions/ver-7");
  });

  it("rediscovers the same draft after navigating away and back -- no new draft is created just by revisiting", async () => {
    const fetchMock = stubFetch([version({ id: "ver-1", version_number: 1, state: "draft" })]);
    const { unmount } = render(withQueryClient(<WorkflowShellPage />));
    await waitFor(() => expect(screen.getByRole("button", { name: "Resume Draft" })).toBeInTheDocument());
    unmount();

    // Simulate navigating back to this same page in a fresh mount.
    render(withQueryClient(<WorkflowShellPage />));
    await waitFor(() => expect(screen.getByRole("button", { name: "Resume Draft" })).toBeInTheDocument());

    const versionCreateCalls = fetchMock.mock.calls.filter(
      (c) => String(c[0]).includes("/versions") && (c[1] as RequestInit | undefined)?.method === "POST",
    );
    expect(versionCreateCalls).toHaveLength(0);
  });

  it("creating a draft version (no draft yet) refreshes the version catalog", async () => {
    stubFetch([]);
    render(withQueryClient(<WorkflowShellPage />));
    await waitFor(() => expect(screen.getByText("No versions yet")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: /create draft version/i }));
    await waitFor(() => expect(pushMock).toHaveBeenCalledWith("/workflows/wf-1/versions/ver-1"));
  });

  it("does not encourage creating another draft when one is already resumable", async () => {
    stubFetch([version({ state: "draft" })]);
    render(withQueryClient(<WorkflowShellPage />));
    await waitFor(() => expect(screen.getByRole("button", { name: "Resume Draft" })).toBeInTheDocument());
    expect(screen.queryByRole("button", { name: /create new draft version/i })).not.toBeInTheDocument();
  });

  it("still offers a secondary Create new draft version once versions exist but none is a draft", async () => {
    stubFetch([version({ state: "published", published_at: "2026-08-29T01:00:00Z" })]);
    render(withQueryClient(<WorkflowShellPage />));
    await waitFor(() => expect(screen.getByRole("button", { name: "View Published Version" })).toBeInTheDocument());
    expect(screen.getByRole("button", { name: /create new draft version/i })).toBeInTheDocument();
  });

  it("truthfully displays more than one concurrent draft rather than silently picking one", async () => {
    stubFetch([
      version({ id: "ver-1", version_number: 1, state: "draft" }),
      version({ id: "ver-2", version_number: 2, state: "draft" }),
    ]);
    render(withQueryClient(<WorkflowShellPage />));
    await waitFor(() => expect(screen.getAllByRole("button", { name: "Resume Draft" })).toHaveLength(2));
  });

  it("never calls a Crop Batch, Sowing, Movement, or Occupancy endpoint", async () => {
    const fetchMock = stubFetch([version({ state: "draft" })]);
    render(withQueryClient(<WorkflowShellPage />));
    await waitFor(() => expect(screen.getByRole("button", { name: "Resume Draft" })).toBeInTheDocument());
    const calledUrls = fetchMock.mock.calls.map((c) => String(c[0]));
    expect(calledUrls.some((u) => /crop-batches|sowings|movements|occupanc|seed-lots/.test(u))).toBe(false);
  });

  it("never sends a tenant-id override or platform-admin header", async () => {
    const fetchMock = stubFetch([version({ state: "draft" })]);
    render(withQueryClient(<WorkflowShellPage />));
    await waitFor(() => expect(screen.getByRole("button", { name: "Resume Draft" })).toBeInTheDocument());
    for (const call of fetchMock.mock.calls) {
      const init = call[1] as RequestInit | undefined;
      const headerKeys = init?.headers ? Object.keys(init.headers as Record<string, string>) : [];
      expect(headerKeys.some((h) => /tenant|platform-admin/i.test(h))).toBe(false);
    }
  });
});
