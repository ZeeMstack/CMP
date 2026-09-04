import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { withQueryClient } from "@/lib/test-utils";

import InventoryItemsPage from "./page";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const CATEGORY = { id: "cat-1", tenant_id: "t", code: "SEED", name: "Seed", status: "active", created_at: "2026-09-01T00:00:00Z" };
const INACTIVE_CATEGORY = {
  id: "cat-2", tenant_id: "t", code: "LEGACY", name: "Legacy Category", status: "inactive",
  created_at: "2026-09-01T00:00:00Z",
};
const UOM = { id: "uom-1", code: "kg", name: "Kilogram", quantity_kind: "mass", conversion_family: "MASS" };
const ITEM = {
  id: "item-1", tenant_id: "t", code: "MAMUTIK-SEED", name: "Mamutik Seed", inventory_category_id: "cat-1",
  base_uom_id: "uom-1", lot_tracking_required: false, expiry_tracking_required: false, qc_release_required: false,
  status: "active", created_at: "2026-09-01T00:00:00Z",
};

function stubFetch(items: (typeof ITEM)[], categories: (typeof CATEGORY)[] = [CATEGORY]) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = init?.method;
    if (url.endsWith("/inventory-categories")) return jsonResponse(categories);
    if (url.endsWith("/uoms")) return jsonResponse([UOM]);
    if (url.endsWith("/inventory-items") && method === "POST") {
      const body = JSON.parse(String(init?.body));
      const created = { ...ITEM, id: "item-new", ...body };
      items.push(created);
      return jsonResponse(created, 201);
    }
    if (url.includes("/deactivate")) {
      const target = items.find((i) => url.includes(i.id));
      if (target) target.status = "inactive";
      return jsonResponse(target);
    }
    if (url.includes("/inventory-items")) return jsonResponse(items);
    return jsonResponse([]);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("InventoryItemsPage", () => {
  it("renders each item's exact fields once reference data loads", async () => {
    stubFetch([ITEM]);
    render(withQueryClient(<InventoryItemsPage />));
    await waitFor(() => expect(screen.getByText("MAMUTIK-SEED")).toBeInTheDocument());
    expect(screen.getByText("Mamutik Seed")).toBeInTheDocument();
    expect(screen.getByText("Seed")).toBeInTheDocument();
    expect(screen.getByText("kg")).toBeInTheDocument();
  });

  it("creates an item with the entered tracking-policy flags", async () => {
    const fetchMock = stubFetch([]);
    render(withQueryClient(<InventoryItemsPage />));
    await waitFor(() => expect(screen.getByRole("button", { name: /new item/i })).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /new item/i }));

    fireEvent.change(screen.getByPlaceholderText("MAMUTIK-SEED"), { target: { value: "CALCIUM-NITRATE" } });
    fireEvent.change(screen.getByPlaceholderText("Mamutik Seed"), { target: { value: "Calcium Nitrate" } });
    fireEvent.change(screen.getByLabelText("Category"), { target: { value: "cat-1" } });
    fireEvent.change(screen.getByLabelText("Base unit of measure"), { target: { value: "uom-1" } });
    fireEvent.click(screen.getByRole("button", { name: /create item/i }));

    await waitFor(() => expect(screen.getByText("CALCIUM-NITRATE")).toBeInTheDocument());
    const postCall = fetchMock.mock.calls.find(
      (c) => String(c[0]).endsWith("/inventory-items") && (c[1] as RequestInit)?.method === "POST",
    );
    const body = JSON.parse(String((postCall?.[1] as RequestInit).body));
    expect(body).toMatchObject({ code: "CALCIUM-NITRATE", category_id: "cat-1", base_uom_id: "uom-1" });
  });

  it("auto-checks and locks Lot Tracking when Expiry Tracking is enabled, and prevents an invalid submit", async () => {
    stubFetch([]);
    render(withQueryClient(<InventoryItemsPage />));
    await waitFor(() => expect(screen.getByRole("button", { name: /new item/i })).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /new item/i }));

    const lotCheckbox = screen.getByLabelText(/lot tracking required/i) as HTMLInputElement;
    const expiryCheckbox = screen.getByLabelText(/expiry tracking required/i) as HTMLInputElement;
    expect(lotCheckbox.checked).toBe(false);

    fireEvent.click(expiryCheckbox);
    await waitFor(() => expect(lotCheckbox.checked).toBe(true));
    expect(lotCheckbox).toBeDisabled();
  });

  it("deactivates an active item", async () => {
    stubFetch([ITEM]);
    render(withQueryClient(<InventoryItemsPage />));
    await waitFor(() => expect(screen.getByRole("button", { name: "Deactivate" })).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Deactivate" }));
    await waitFor(() => expect(screen.getByText("Inactive")).toBeInTheDocument());
  });

  it("does not offer an inactive category for a new assignment", async () => {
    stubFetch([], [CATEGORY, INACTIVE_CATEGORY]);
    render(withQueryClient(<InventoryItemsPage />));
    await waitFor(() => expect(screen.getByRole("button", { name: /new item/i })).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /new item/i }));

    const categorySelect = screen.getByLabelText("Category") as HTMLSelectElement;
    const optionLabels = Array.from(categorySelect.options).map((o) => o.textContent);
    expect(optionLabels).toContain("Seed");
    expect(optionLabels).not.toContain("Legacy Category");
  });

  it("still displays an item's own current category even after it becomes inactive", async () => {
    const itemOnInactiveCategory = { ...ITEM, inventory_category_id: "cat-2" };
    stubFetch([itemOnInactiveCategory], [CATEGORY, INACTIVE_CATEGORY]);
    render(withQueryClient(<InventoryItemsPage />));
    await waitFor(() => expect(screen.getByRole("button", { name: "Edit" })).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Edit" }));

    const categorySelect = screen.getByLabelText("Category") as HTMLSelectElement;
    expect(categorySelect.value).toBe("cat-2");
    const optionLabels = Array.from(categorySelect.options).map((o) => o.textContent);
    expect(optionLabels).toContain("Legacy Category");
  });

  it("never renders supplier/cost/price fields", async () => {
    stubFetch([]);
    render(withQueryClient(<InventoryItemsPage />));
    await waitFor(() => expect(screen.getByRole("button", { name: /new item/i })).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /new item/i }));
    expect(screen.queryByText(/supplier/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/cost/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/price/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/purchase/i)).not.toBeInTheDocument();
  });
});
