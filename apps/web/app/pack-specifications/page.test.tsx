import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const pushMock = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock }),
}));

import { withQueryClient } from "@/lib/test-utils";

import PackSpecificationsPage from "./page";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const CROP = { id: "crop-1", tenant_id: "t", code: "ICE", common_name: "Iceberg Lettuce", scientific_name: null, crop_category: "leafy_green", status: "active" };
const SPEC = {
  id: "ps-1", tenant_id: "t", crop_id: "crop-1", variety_id: null, code: "ICE-5KG", name: "Iceberg 5kg",
  customer_reference: null, created_at: "2026-08-29T00:00:00Z",
};

function stubFetch(specs: unknown[]) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = init?.method;
    if (url.endsWith("/pack-specifications") && method === "POST") {
      const body = JSON.parse(String(init?.body));
      if (specs.some((s) => (s as { code: string }).code === body.code)) {
        return jsonResponse({ detail: "Pack specification code already exists in this tenant" }, 409);
      }
      const created = { ...SPEC, id: "ps-new", code: body.code, name: body.name, crop_id: body.crop_id, variety_id: body.variety_id, customer_reference: body.customer_reference };
      specs.push(created);
      return jsonResponse(created, 201);
    }
    if (url.includes("/pack-specifications")) return jsonResponse(specs);
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

describe("PackSpecificationsPage", () => {
  it("renders each pack specification joined against its Crop", async () => {
    stubFetch([SPEC]);
    render(withQueryClient(<PackSpecificationsPage />));
    await waitFor(() => expect(screen.getByText("ICE-5KG")).toBeInTheDocument());
    expect(screen.getByText("Iceberg Lettuce (ICE)")).toBeInTheDocument();
  });

  it("shows empty state with no pack specifications", async () => {
    stubFetch([]);
    render(withQueryClient(<PackSpecificationsPage />));
    await waitFor(() => expect(screen.getByText("No pack specifications yet")).toBeInTheDocument());
  });

  it("creates a pack specification with exact fields and navigates to its detail page", async () => {
    const fetchMock = stubFetch([]);
    render(withQueryClient(<PackSpecificationsPage />));
    await waitFor(() => expect(screen.getByText("No pack specifications yet")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: /new pack specification/i }));
    fireEvent.change(screen.getByPlaceholderText("ICE-5KG-CARTON"), { target: { value: "ICE-10KG" } });
    fireEvent.change(screen.getByPlaceholderText("Iceberg 5kg Carton"), { target: { value: "Iceberg 10kg" } });
    fireEvent.change(screen.getByLabelText("Crop"), { target: { value: "crop-1" } });
    fireEvent.click(screen.getByRole("button", { name: /create pack specification/i }));

    await waitFor(() => expect(pushMock).toHaveBeenCalledWith("/pack-specifications/ps-new"));
    const postCall = fetchMock.mock.calls.find(
      (c) => String(c[0]).endsWith("/pack-specifications") && (c[1] as RequestInit)?.method === "POST",
    );
    const body = JSON.parse(String((postCall?.[1] as RequestInit).body));
    expect(body).toMatchObject({ code: "ICE-10KG", name: "Iceberg 10kg", crop_id: "crop-1", variety_id: null, customer_reference: null });
  });

  it("surfaces a duplicate-code conflict without losing the form", async () => {
    stubFetch([SPEC]);
    render(withQueryClient(<PackSpecificationsPage />));
    await waitFor(() => expect(screen.getByText("ICE-5KG")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: /new pack specification/i }));
    fireEvent.change(screen.getByPlaceholderText("ICE-5KG-CARTON"), { target: { value: "ICE-5KG" } });
    fireEvent.change(screen.getByPlaceholderText("Iceberg 5kg Carton"), { target: { value: "Dup" } });
    fireEvent.change(screen.getByLabelText("Crop"), { target: { value: "crop-1" } });
    fireEvent.click(screen.getByRole("button", { name: /create pack specification/i }));

    await waitFor(() =>
      expect(screen.getByText("Pack specification code already exists in this tenant")).toBeInTheDocument(),
    );
  });

  it("never calls a packing or finished-goods operational endpoint", async () => {
    const fetchMock = stubFetch([SPEC]);
    render(withQueryClient(<PackSpecificationsPage />));
    await waitFor(() => expect(screen.getByText("ICE-5KG")).toBeInTheDocument());
    const urls = fetchMock.mock.calls.map((c) => String(c[0]));
    expect(urls.some((u) => /packing-events|finished-goods|dispatch/.test(u))).toBe(false);
  });
});
