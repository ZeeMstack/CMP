import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { withQueryClient } from "@/lib/test-utils";

import SettingsWorkspacePage from "./page";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const CATEGORY = { id: "cat-1", tenant_id: "t", code: "SEED", name: "Seed", status: "active", created_at: "2026-09-01T00:00:00Z" };
const UOM = { id: "uom-1", code: "kg", name: "Kilogram", quantity_kind: "mass", conversion_family: "MASS" };

function stubFetch() {
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.endsWith("/inventory-categories")) return jsonResponse([CATEGORY]);
    if (url.endsWith("/uoms")) return jsonResponse([UOM]);
    return jsonResponse([]);
  });
  vi.stubGlobal("fetch", fetchMock);
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("SettingsWorkspacePage", () => {
  it("renders Categories management and the read-only UOM reference together", async () => {
    stubFetch();
    render(withQueryClient(<SettingsWorkspacePage />));
    await waitFor(() => expect(screen.getByText("Seed")).toBeInTheDocument());
    expect(screen.getByText("Rename")).toBeInTheDocument();
    expect(screen.getByText("kg")).toBeInTheDocument();
    expect(screen.getByText("System reference")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /edit/i })).not.toBeInTheDocument();
  });
});
