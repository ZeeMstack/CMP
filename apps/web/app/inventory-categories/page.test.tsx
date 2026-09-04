import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { withQueryClient } from "@/lib/test-utils";

import InventoryCategoriesPage from "./page";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const CATEGORY = { id: "cat-1", tenant_id: "t", code: "SEED", name: "Seed", status: "active", created_at: "2026-09-01T00:00:00Z" };

function stubFetch(categories: (typeof CATEGORY)[]) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = init?.method;
    if (url.endsWith("/inventory-categories") && method === "POST") {
      const body = JSON.parse(String(init?.body));
      if (categories.some((c) => c.code.toLowerCase() === String(body.code).toLowerCase())) {
        return jsonResponse({ detail: "Inventory category code already exists in this tenant" }, 409);
      }
      const created = { ...CATEGORY, id: "cat-new", code: body.code, name: body.name };
      categories.push(created);
      return jsonResponse(created, 201);
    }
    if (url.includes("/deactivate")) {
      const target = categories.find((c) => url.includes(c.id));
      if (target) target.status = "inactive";
      return jsonResponse(target);
    }
    if (url.includes("/reactivate")) {
      const target = categories.find((c) => url.includes(c.id));
      if (target) target.status = "active";
      return jsonResponse(target);
    }
    if (url.includes("/update")) {
      const target = categories.find((c) => url.includes(c.id));
      const body = JSON.parse(String(init?.body));
      if (target) target.name = body.name;
      return jsonResponse(target);
    }
    if (url.includes("/inventory-categories")) return jsonResponse(categories);
    return jsonResponse([]);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("InventoryCategoriesPage", () => {
  it("renders each category's exact fields", async () => {
    stubFetch([CATEGORY]);
    render(withQueryClient(<InventoryCategoriesPage />));
    await waitFor(() => expect(screen.getByText("SEED")).toBeInTheDocument());
    expect(screen.getByText("Seed")).toBeInTheDocument();
    expect(screen.getByText("Active")).toBeInTheDocument();
  });

  it("shows empty state with no categories", async () => {
    stubFetch([]);
    render(withQueryClient(<InventoryCategoriesPage />));
    await waitFor(() => expect(screen.getByText("No inventory categories yet")).toBeInTheDocument());
  });

  it("creates a category and refreshes the list", async () => {
    const fetchMock = stubFetch([]);
    render(withQueryClient(<InventoryCategoriesPage />));
    await waitFor(() => expect(screen.getByText("No inventory categories yet")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: /new category/i }));
    fireEvent.change(screen.getByPlaceholderText("SEED"), { target: { value: "CHEMICAL" } });
    fireEvent.change(screen.getByPlaceholderText("Seed"), { target: { value: "Chemical" } });
    fireEvent.click(screen.getByRole("button", { name: /create category/i }));

    await waitFor(() => expect(screen.getByText("CHEMICAL")).toBeInTheDocument());
    const postCall = fetchMock.mock.calls.find(
      (c) => String(c[0]).endsWith("/inventory-categories") && (c[1] as RequestInit)?.method === "POST",
    );
    const body = JSON.parse(String((postCall?.[1] as RequestInit).body));
    expect(body).toMatchObject({ code: "CHEMICAL", name: "Chemical" });
  });

  it("deactivates then reactivates a category", async () => {
    stubFetch([CATEGORY]);
    render(withQueryClient(<InventoryCategoriesPage />));
    await waitFor(() => expect(screen.getByRole("button", { name: "Deactivate" })).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Deactivate" }));
    await waitFor(() => expect(screen.getByText("Inactive")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "Reactivate" }));
    await waitFor(() => expect(screen.getByText("Active")).toBeInTheDocument());
  });
});
