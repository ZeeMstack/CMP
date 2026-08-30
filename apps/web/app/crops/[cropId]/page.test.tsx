import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useParams: () => ({ cropId: "crop-1" }),
}));

import { withQueryClient } from "@/lib/test-utils";

import CropVarietiesPage from "./page";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const CROP = {
  id: "crop-1", tenant_id: "t", code: "ICE", common_name: "Iceberg Lettuce",
  scientific_name: null, crop_category: "leafy_green", status: "active",
};

function variety(overrides: Partial<Record<string, unknown>> = {}) {
  return { id: "var-1", tenant_id: "t", crop_id: "crop-1", code: "MAM", name: "Mamutik", supplier_reference: null, status: "active", ...overrides };
}

function stubFetch(varieties: unknown[], postResult?: { status: number; body: unknown }) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.includes("/varieties") && init?.method === "POST") {
        return postResult ? jsonResponse(postResult.body, postResult.status) : jsonResponse(variety());
      }
      if (url.includes("/varieties")) return jsonResponse(varieties);
      if (url.includes("/crops")) return jsonResponse([CROP]);
      return jsonResponse([]);
    }),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("CropVarietiesPage", () => {
  it("renders varieties scoped to this crop", async () => {
    stubFetch([variety()]);
    render(withQueryClient(<CropVarietiesPage />));
    await waitFor(() => expect(screen.getByText("MAM")).toBeInTheDocument());
    expect(screen.getByText("Iceberg Lettuce — Varieties")).toBeInTheDocument();
  });

  it("creates a variety against this crop and refreshes the list", async () => {
    stubFetch([]);
    render(withQueryClient(<CropVarietiesPage />));
    await waitFor(() => expect(screen.getByText("No varieties yet")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: /new variety/i }));
    fireEvent.change(screen.getByLabelText("Code"), { target: { value: "mam" } });
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Mamutik" } });

    stubFetch([variety()]);
    fireEvent.click(screen.getByRole("button", { name: /create variety/i }));

    await waitFor(() => expect(screen.getByText("Mamutik")).toBeInTheDocument());
  });

  it("surfaces a duplicate variety code conflict", async () => {
    stubFetch([], { status: 409, body: { detail: "Variety code already exists for this crop" } });
    render(withQueryClient(<CropVarietiesPage />));
    await waitFor(() => expect(screen.getByText("No varieties yet")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: /new variety/i }));
    fireEvent.change(screen.getByLabelText("Code"), { target: { value: "mam" } });
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Mamutik" } });
    fireEvent.click(screen.getByRole("button", { name: /create variety/i }));

    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Variety code already exists for this crop"));
  });

  it("optional supplier reference renders as em dash when absent, never blocking the row", async () => {
    stubFetch([variety({ supplier_reference: null })]);
    render(withQueryClient(<CropVarietiesPage />));
    await waitFor(() => expect(screen.getByText("MAM")).toBeInTheDocument());
    expect(screen.getByText("—")).toBeInTheDocument();
  });

  it("has no Seed Lot registration entry point on this page", async () => {
    stubFetch([variety()]);
    render(withQueryClient(<CropVarietiesPage />));
    await waitFor(() => expect(screen.getByText("MAM")).toBeInTheDocument());
    expect(screen.queryByText(/seed lot/i)).not.toBeInTheDocument();
  });
});
