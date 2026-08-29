import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "gd-1" }),
}));

import { withQueryClient } from "@/lib/test-utils";

import GradeDefinitionDetailPage from "./page";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const DEFINITION = {
  id: "gd-1", tenant_id: "t", crop_id: "crop-1", variety_id: null, code: "CLASS-1", name: "Class 1",
  description: "Top grade", created_at: "2026-08-29T00:00:00Z",
};
const CROP = { id: "crop-1", tenant_id: "t", code: "ICE", common_name: "Iceberg Lettuce", scientific_name: null, crop_category: "leafy_green", status: "active" };

function version(overrides: Partial<Record<string, unknown>> = {}) {
  return {
    id: "gdv-1", tenant_id: "t", grade_definition_id: "gd-1", version_number: 1, status: "draft",
    effective_from: null as string | null, effective_until: null as string | null, spec_notes: null, created_by: null,
    created_at: "2026-08-29T00:00:00Z", ...overrides,
  };
}

function stubFetch(versions: ReturnType<typeof version>[]) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = init?.method;
    if (url.includes("/versions") && url.includes("/activate")) {
      const target = versions.find((v) => url.includes(v.id as string));
      if (target) {
        target.status = "active";
        target.effective_from = "2026-08-29T00:00:00Z";
      }
      return jsonResponse(target);
    }
    if (url.includes("/versions") && url.includes("/retire")) {
      const target = versions.find((v) => url.includes(v.id as string));
      if (target) {
        target.status = "retired";
        target.effective_until = "2026-08-29T01:00:00Z";
      }
      return jsonResponse(target);
    }
    if (url.includes("/versions") && method === "POST") {
      const body = JSON.parse(String(init?.body));
      const created = version({ id: `gdv-${versions.length + 1}`, version_number: versions.length + 1, spec_notes: body.spec_notes });
      versions.push(created);
      return jsonResponse(created, 201);
    }
    if (url.includes("/versions")) return jsonResponse(versions);
    if (url.includes("/grade-definitions")) return jsonResponse([DEFINITION]);
    if (url.includes("/crops")) return jsonResponse([CROP]);
    return jsonResponse([]);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("GradeDefinitionDetailPage", () => {
  it("shows the definition's identity and its version catalog", async () => {
    stubFetch([version({ status: "active", effective_from: "2026-08-29T00:00:00Z" })]);
    render(withQueryClient(<GradeDefinitionDetailPage />));
    await waitFor(() => expect(screen.getByText("CLASS-1")).toBeInTheDocument());
    expect(screen.getByText("Iceberg Lettuce (ICE)")).toBeInTheDocument();
    expect(screen.getByText("Active")).toBeInTheDocument();
  });

  it("creates a draft version and rediscovers it after navigating away and back", async () => {
    const fetchMock = stubFetch([]);
    const { unmount } = render(withQueryClient(<GradeDefinitionDetailPage />));
    await waitFor(() => expect(screen.getByText("No versions yet")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "Create draft version" }));
    fireEvent.change(screen.getByLabelText("Spec notes (optional)"), { target: { value: "Firm heads, no blemish" } });
    fireEvent.click(screen.getByRole("button", { name: /^create draft version$/i }));

    await waitFor(() => expect(screen.getByRole("button", { name: "Review & activate" })).toBeInTheDocument());
    unmount();

    render(withQueryClient(<GradeDefinitionDetailPage />));
    await waitFor(() => expect(screen.getByRole("button", { name: "Review & activate" })).toBeInTheDocument());

    const createCalls = fetchMock.mock.calls.filter(
      (c) => String(c[0]).includes("/versions") && (c[1] as RequestInit | undefined)?.method === "POST",
    );
    expect(createCalls).toHaveLength(1);
  });

  it("never auto-activates a newly created draft version", async () => {
    stubFetch([]);
    render(withQueryClient(<GradeDefinitionDetailPage />));
    await waitFor(() => expect(screen.getByText("No versions yet")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Create draft version" }));
    fireEvent.click(screen.getByRole("button", { name: /^create draft version$/i }));
    await waitFor(() => expect(screen.getByText("Draft")).toBeInTheDocument());
    expect(screen.queryByText("Active")).not.toBeInTheDocument();
  });

  it("activation is explicit: requires opening Review & activate and confirming an effective date/time", async () => {
    const fetchMock = stubFetch([version({ id: "gdv-1", status: "draft" })]);
    render(withQueryClient(<GradeDefinitionDetailPage />));
    await waitFor(() => expect(screen.getByRole("button", { name: "Review & activate" })).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "Review & activate" }));
    expect(screen.getByText("Activate version 1")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Effective date"), { target: { value: "2026-08-29" } });
    fireEvent.change(screen.getByLabelText("Effective time"), { target: { value: "10:00" } });
    fireEvent.click(screen.getByRole("button", { name: "Activate version" }));

    await waitFor(() => expect(screen.getByText("Active")).toBeInTheDocument());
    const activateCall = fetchMock.mock.calls.find((c) => String(c[0]).endsWith("/versions/gdv-1/activate"));
    expect(activateCall).toBeDefined();
    const body = JSON.parse(String((activateCall?.[1] as RequestInit).body));
    expect(typeof body.client_command_id).toBe("string");
    expect(body.effective_time).toContain("2026-08-29");
  });

  it("an active version offers Retire, a retired version offers no action", async () => {
    stubFetch([version({ status: "active", effective_from: "2026-08-29T00:00:00Z" })]);
    render(withQueryClient(<GradeDefinitionDetailPage />));
    await waitFor(() => expect(screen.getByRole("button", { name: "Retire" })).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "Retire" }));
    expect(screen.getByText("Retire version 1")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Effective date"), { target: { value: "2026-08-29" } });
    fireEvent.change(screen.getByLabelText("Effective time"), { target: { value: "11:00" } });
    fireEvent.click(screen.getByRole("button", { name: "Retire version" }));

    await waitFor(() => expect(screen.getByText("Retired")).toBeInTheDocument());
    const row = screen.getByText("v1").closest("tr") as HTMLElement;
    expect(within(row).queryByRole("button")).not.toBeInTheDocument();
  });

  it("never calls a grading, packing, harvest, or finished-goods operational endpoint", async () => {
    const fetchMock = stubFetch([version({ status: "active", effective_from: "2026-08-29T00:00:00Z" })]);
    render(withQueryClient(<GradeDefinitionDetailPage />));
    await waitFor(() => expect(screen.getByText("Active")).toBeInTheDocument());
    const urls = fetchMock.mock.calls.map((c) => String(c[0]));
    expect(urls.some((u) => /grading-events|graded-produce-lots|packing-events|harvest|finished-goods|cold-storage|dispatch/.test(u))).toBe(false);
  });
});
