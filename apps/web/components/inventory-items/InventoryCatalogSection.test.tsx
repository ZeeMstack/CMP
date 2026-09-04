import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { withQueryClient } from "@/lib/test-utils";

import { InventoryCatalogSection } from "./InventoryCatalogSection";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

function stubFetch() {
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.endsWith("/inventory-categories")) return jsonResponse([]);
    if (url.endsWith("/uoms")) return jsonResponse([]);
    if (url.endsWith("/inventory-items")) return jsonResponse([]);
    return jsonResponse([]);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("InventoryCatalogSection prerequisite CTA", () => {
  it("offers a direct action to the Categories manager when none is active, not text-only guidance", async () => {
    stubFetch();
    render(withQueryClient(<InventoryCatalogSection categoriesHref="/farms/farm-1/store-inventory-setup/settings" />));
    await waitFor(() => expect(screen.getByText("No active Inventory Categories")).toBeInTheDocument());
    const link = screen.getByRole("link", { name: "Create / Manage Categories" });
    expect(link).toHaveAttribute("href", "/farms/farm-1/store-inventory-setup/settings");
  });
});
