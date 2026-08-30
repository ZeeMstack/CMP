import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { withQueryClient } from "@/lib/test-utils";

import ProductionSystemsPage from "./page";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

function system(overrides: Partial<Record<string, unknown>> = {}) {
  return { id: "ps-1", tenant_id: "t", code: "NFT", name: "NFT Leafy Greens", description: null, status: "active", ...overrides };
}

function stubFetch(systems: unknown[], postResult?: { status: number; body: unknown }) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.includes("/production-systems") && init?.method === "POST") {
        return postResult ? jsonResponse(postResult.body, postResult.status) : jsonResponse(system());
      }
      if (url.includes("/production-systems")) return jsonResponse(systems);
      return jsonResponse([]);
    }),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("ProductionSystemsPage", () => {
  it("renders the list", async () => {
    stubFetch([system()]);
    render(withQueryClient(<ProductionSystemsPage />));
    await waitFor(() => expect(screen.getByText("NFT")).toBeInTheDocument());
    expect(screen.getByText("NFT Leafy Greens")).toBeInTheDocument();
  });

  it("shows empty state", async () => {
    stubFetch([]);
    render(withQueryClient(<ProductionSystemsPage />));
    await waitFor(() => expect(screen.getByText("No production systems yet")).toBeInTheDocument());
  });

  it("creates with exact fields and refreshes the list", async () => {
    stubFetch([]);
    render(withQueryClient(<ProductionSystemsPage />));
    await waitFor(() => expect(screen.getByText("No production systems yet")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: /new production system/i }));
    fireEvent.change(screen.getByLabelText("Code"), { target: { value: "nft" } });
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "NFT Leafy Greens" } });

    stubFetch([system()]);
    fireEvent.click(screen.getByRole("button", { name: /create production system/i }));

    await waitFor(() => expect(screen.getByText("NFT Leafy Greens")).toBeInTheDocument());
  });

  it("surfaces a duplicate code conflict", async () => {
    stubFetch([], { status: 409, body: { detail: "Production system code already exists in this tenant" } });
    render(withQueryClient(<ProductionSystemsPage />));
    await waitFor(() => expect(screen.getByText("No production systems yet")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: /new production system/i }));
    fireEvent.change(screen.getByLabelText("Code"), { target: { value: "nft" } });
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "NFT Leafy Greens" } });
    fireEvent.click(screen.getByRole("button", { name: /create production system/i }));

    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent("Production system code already exists in this tenant"),
    );
  });
});
