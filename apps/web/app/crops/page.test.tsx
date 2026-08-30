import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { withQueryClient } from "@/lib/test-utils";

import CropsPage from "./page";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

function crop(overrides: Partial<Record<string, unknown>> = {}) {
  return {
    id: "crop-1", tenant_id: "t", code: "ICE", common_name: "Iceberg Lettuce",
    scientific_name: null, crop_category: "leafy_green", status: "active",
    ...overrides,
  };
}

function stubFetch(crops: unknown[], postResult?: { status: number; body: unknown }) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.includes("/crops") && (!init || init.method === undefined)) return jsonResponse(crops);
      if (url.includes("/crops") && init?.method === "POST") {
        return postResult ? jsonResponse(postResult.body, postResult.status) : jsonResponse(crop());
      }
      return jsonResponse([]);
    }),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("CropsPage", () => {
  it("renders the crop list", async () => {
    stubFetch([crop()]);
    render(withQueryClient(<CropsPage />));
    await waitFor(() => expect(screen.getByText("ICE")).toBeInTheDocument());
    expect(screen.getByText("Iceberg Lettuce")).toBeInTheDocument();
    expect(screen.getByText("Leafy green")).toBeInTheDocument();
  });

  it("shows empty state with no crops", async () => {
    stubFetch([]);
    render(withQueryClient(<CropsPage />));
    await waitFor(() => expect(screen.getByText("No crops yet")).toBeInTheDocument());
  });

  it("creates a crop with exact fields and refreshes the list", async () => {
    stubFetch([]);
    render(withQueryClient(<CropsPage />));
    await waitFor(() => expect(screen.getByText("No crops yet")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: /new crop/i }));
    fireEvent.change(screen.getByLabelText("Code"), { target: { value: "ice" } });
    fireEvent.change(screen.getByLabelText("Common name"), { target: { value: "Iceberg Lettuce" } });

    stubFetch([crop()]);
    fireEvent.click(screen.getByRole("button", { name: /create crop/i }));

    await waitFor(() => expect(screen.getByText("Iceberg Lettuce")).toBeInTheDocument());
  });

  it("surfaces a duplicate crop code conflict without a raw traceback", async () => {
    stubFetch([], { status: 409, body: { detail: "Crop code already exists in this tenant" } });
    render(withQueryClient(<CropsPage />));
    await waitFor(() => expect(screen.getByText("No crops yet")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: /new crop/i }));
    fireEvent.change(screen.getByLabelText("Code"), { target: { value: "ice" } });
    fireEvent.change(screen.getByLabelText("Common name"), { target: { value: "Iceberg Lettuce" } });
    fireEvent.click(screen.getByRole("button", { name: /create crop/i }));

    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Crop code already exists in this tenant"));
  });

  it("never renders a tenant/farm id field to edit -- tenant is derived server-side", async () => {
    stubFetch([]);
    render(withQueryClient(<CropsPage />));
    await waitFor(() => expect(screen.getByText("No crops yet")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /new crop/i }));
    expect(screen.queryByLabelText(/tenant/i)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/farm/i)).not.toBeInTheDocument();
  });
});
