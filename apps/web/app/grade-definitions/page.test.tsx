import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const pushMock = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock }),
}));

import { withQueryClient } from "@/lib/test-utils";

import GradeDefinitionsPage from "./page";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const CROP = { id: "crop-1", tenant_id: "t", code: "ICE", common_name: "Iceberg Lettuce", scientific_name: null, crop_category: "leafy_green", status: "active" };
const DEFINITION = {
  id: "gd-1", tenant_id: "t", crop_id: "crop-1", variety_id: null, code: "CLASS-1", name: "Class 1",
  description: null, created_at: "2026-08-29T00:00:00Z",
};

/** `definitions`/`versions` mutable so a POST test can assert the created
 * row shows up, mirroring `WorkflowShellPage`'s own `stubFetch` shape. */
function stubFetch(definitions: unknown[]) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = init?.method;
    if (url.endsWith("/grade-definitions") && method === "POST") {
      const body = JSON.parse(String(init?.body));
      if (definitions.some((d) => (d as { code: string }).code === body.code)) {
        return jsonResponse({ detail: "Grade definition code already exists in this tenant" }, 409);
      }
      const created = { ...DEFINITION, id: "gd-new", code: body.code, name: body.name, crop_id: body.crop_id, variety_id: body.variety_id, description: body.description };
      definitions.push(created);
      return jsonResponse(created, 201);
    }
    if (url.includes("/grade-definitions")) return jsonResponse(definitions);
    if (url.includes("/crops")) return jsonResponse([CROP]);
    return jsonResponse([]);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => {
  vi.unstubAllGlobals();
  pushMock.mockClear();
});

describe("GradeDefinitionsPage", () => {
  it("renders each grade definition joined against its Crop", async () => {
    stubFetch([DEFINITION]);
    render(withQueryClient(<GradeDefinitionsPage />));
    await waitFor(() => expect(screen.getByText("CLASS-1")).toBeInTheDocument());
    expect(screen.getByText("Iceberg Lettuce (ICE)")).toBeInTheDocument();
  });

  it("shows empty state with no grade definitions", async () => {
    stubFetch([]);
    render(withQueryClient(<GradeDefinitionsPage />));
    await waitFor(() => expect(screen.getByText("No grade definitions yet")).toBeInTheDocument());
  });

  it("creates a grade definition with exact fields and navigates to its detail page", async () => {
    const fetchMock = stubFetch([]);
    render(withQueryClient(<GradeDefinitionsPage />));
    await waitFor(() => expect(screen.getByText("No grade definitions yet")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: /new grade definition/i }));
    fireEvent.change(screen.getByPlaceholderText("ICE-CLASS-1"), { target: { value: "class-2" } });
    fireEvent.change(screen.getByPlaceholderText("Iceberg Class 1"), { target: { value: "Class 2" } });
    fireEvent.change(screen.getByLabelText("Crop"), { target: { value: "crop-1" } });
    fireEvent.click(screen.getByRole("button", { name: /create grade definition/i }));

    await waitFor(() => expect(pushMock).toHaveBeenCalledWith("/grade-definitions/gd-new"));
    const postCall = fetchMock.mock.calls.find(
      (c) => String(c[0]).endsWith("/grade-definitions") && (c[1] as RequestInit)?.method === "POST",
    );
    const body = JSON.parse(String((postCall?.[1] as RequestInit).body));
    expect(body).toMatchObject({ code: "class-2", name: "Class 2", crop_id: "crop-1", variety_id: null, description: null });
    expect(typeof body.client_command_id).toBe("string");
  });

  it("surfaces a duplicate-code conflict without losing the form", async () => {
    stubFetch([DEFINITION]);
    render(withQueryClient(<GradeDefinitionsPage />));
    await waitFor(() => expect(screen.getByText("CLASS-1")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: /new grade definition/i }));
    fireEvent.change(screen.getByPlaceholderText("ICE-CLASS-1"), { target: { value: "CLASS-1" } });
    fireEvent.change(screen.getByPlaceholderText("Iceberg Class 1"), { target: { value: "Class 1 dup" } });
    fireEvent.change(screen.getByLabelText("Crop"), { target: { value: "crop-1" } });
    fireEvent.click(screen.getByRole("button", { name: /create grade definition/i }));

    await waitFor(() =>
      expect(screen.getByText("Grade definition code already exists in this tenant")).toBeInTheDocument(),
    );
    expect(screen.getByPlaceholderText("Iceberg Class 1")).toHaveValue("Class 1 dup");
  });

  it("never calls a grading, packing, or harvest operational endpoint", async () => {
    const fetchMock = stubFetch([DEFINITION]);
    render(withQueryClient(<GradeDefinitionsPage />));
    await waitFor(() => expect(screen.getByText("CLASS-1")).toBeInTheDocument());
    const urls = fetchMock.mock.calls.map((c) => String(c[0]));
    expect(urls.some((u) => /grading-events|graded-produce-lots|packing-events|harvest/.test(u))).toBe(false);
  });
});
