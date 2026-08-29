import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { withQueryClient } from "@/lib/test-utils";

import PackagingUnitsPage from "./page";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const UNIT = { id: "pu-1", tenant_id: "t", code: "CARTON-5KG", name: "5kg Carton", status: "active", created_at: "2026-08-29T00:00:00Z" };

function stubFetch(units: (typeof UNIT)[]) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = init?.method;
    if (url.endsWith("/packaging-units") && method === "POST") {
      const body = JSON.parse(String(init?.body));
      if (units.some((u) => u.code.toLowerCase() === String(body.code).toLowerCase())) {
        return jsonResponse({ detail: "Packaging unit code already exists in this tenant" }, 409);
      }
      const created = { ...UNIT, id: "pu-new", code: body.code, name: body.name };
      units.push(created);
      return jsonResponse(created, 201);
    }
    if (url.includes("/retire")) {
      const target = units.find((u) => url.includes(u.id));
      if (target) target.status = "retired";
      return jsonResponse(target);
    }
    if (url.includes("/packaging-units")) return jsonResponse(units);
    return jsonResponse([]);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("PackagingUnitsPage", () => {
  it("renders each packaging unit's exact fields", async () => {
    stubFetch([UNIT]);
    render(withQueryClient(<PackagingUnitsPage />));
    await waitFor(() => expect(screen.getByText("CARTON-5KG")).toBeInTheDocument());
    expect(screen.getByText("5kg Carton")).toBeInTheDocument();
    expect(screen.getByText("Active")).toBeInTheDocument();
  });

  it("shows empty state with no packaging units", async () => {
    stubFetch([]);
    render(withQueryClient(<PackagingUnitsPage />));
    await waitFor(() => expect(screen.getByText("No packaging units yet")).toBeInTheDocument());
  });

  it("creates a packaging unit and refreshes the list", async () => {
    const fetchMock = stubFetch([]);
    render(withQueryClient(<PackagingUnitsPage />));
    await waitFor(() => expect(screen.getByText("No packaging units yet")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: /new packaging unit/i }));
    fireEvent.change(screen.getByPlaceholderText("CARTON-5KG"), { target: { value: "CRATE-10KG" } });
    fireEvent.change(screen.getByPlaceholderText("5kg Carton"), { target: { value: "10kg Crate" } });
    fireEvent.click(screen.getByRole("button", { name: /create packaging unit/i }));

    await waitFor(() => expect(screen.getByText("CRATE-10KG")).toBeInTheDocument());
    const postCall = fetchMock.mock.calls.find(
      (c) => String(c[0]).endsWith("/packaging-units") && (c[1] as RequestInit)?.method === "POST",
    );
    const body = JSON.parse(String((postCall?.[1] as RequestInit).body));
    expect(body).toMatchObject({ code: "CRATE-10KG", name: "10kg Crate" });
    expect(typeof body.client_command_id).toBe("string");
  });

  it("surfaces a duplicate-code conflict", async () => {
    stubFetch([UNIT]);
    render(withQueryClient(<PackagingUnitsPage />));
    await waitFor(() => expect(screen.getByText("CARTON-5KG")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: /new packaging unit/i }));
    fireEvent.change(screen.getByPlaceholderText("CARTON-5KG"), { target: { value: "CARTON-5KG" } });
    fireEvent.change(screen.getByPlaceholderText("5kg Carton"), { target: { value: "Dup" } });
    fireEvent.click(screen.getByRole("button", { name: /create packaging unit/i }));

    await waitFor(() =>
      expect(screen.getByText("Packaging unit code already exists in this tenant")).toBeInTheDocument(),
    );
  });

  it("retires an active packaging unit explicitly", async () => {
    stubFetch([UNIT]);
    render(withQueryClient(<PackagingUnitsPage />));
    await waitFor(() => expect(screen.getByRole("button", { name: "Retire" })).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Retire" }));
    await waitFor(() => expect(screen.getByText("Retired")).toBeInTheDocument());
    expect(screen.queryByRole("button", { name: "Retire" })).not.toBeInTheDocument();
  });

  it("never renders a pack-size (weight/units) field on the Packaging Unit form", async () => {
    stubFetch([]);
    render(withQueryClient(<PackagingUnitsPage />));
    await waitFor(() => expect(screen.getByText("No packaging units yet")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /new packaging unit/i }));
    expect(screen.queryByText(/nominal net weight/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/whole units per pack/i)).not.toBeInTheDocument();
  });

  it("never calls a packing operational endpoint", async () => {
    const fetchMock = stubFetch([UNIT]);
    render(withQueryClient(<PackagingUnitsPage />));
    await waitFor(() => expect(screen.getByText("CARTON-5KG")).toBeInTheDocument());
    const urls = fetchMock.mock.calls.map((c) => String(c[0]));
    expect(urls.some((u) => /packing-events|finished-goods/.test(u))).toBe(false);
  });
});
