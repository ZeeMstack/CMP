import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const pushMock = vi.fn();
vi.mock("next/navigation", () => ({
  useParams: () => ({ farmId: "farm-1" }),
  useRouter: () => ({ push: pushMock }),
}));

import { withQueryClient } from "@/lib/test-utils";

import NewSeedLotPage from "./page";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const CROPS = [{ id: "crop-1", tenant_id: "t", code: "ICE", common_name: "Iceberg Lettuce", scientific_name: null, crop_category: "leafy_green", status: "active" }];
const VARIETIES = [{ id: "var-1", tenant_id: "t", crop_id: "crop-1", code: "MAM", name: "Mamutik", supplier_reference: null, status: "active" }];

function stubFetch() {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (init?.method === "POST" && url.includes("/seed-lots")) {
        return jsonResponse(
          {
            id: "lot-new", tenant_id: "t", farm_id: "f", code: "RZ-MAM-2026-001",
            crop: CROPS[0], variety: VARIETIES[0],
            supplier_name: null, supplier_lot_reference: null, received_date: null, expiry_date: null,
            status: "active", created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z",
          },
          201,
        );
      }
      if (url.includes("/api/crops/crop-1/varieties")) return jsonResponse(VARIETIES);
      if (url.includes("/api/crops")) return jsonResponse(CROPS);
      return jsonResponse([]);
    }),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
  pushMock.mockClear();
});

describe("NewSeedLotPage: compact guided create command", () => {
  it("saves the Seed Lot and redirects to its detail page", async () => {
    stubFetch();
    render(withQueryClient(<NewSeedLotPage />));
    await waitFor(() => expect(screen.getByText("Iceberg Lettuce")).toBeInTheDocument());

    fireEvent.change(screen.getByLabelText(/^crop$/i), { target: { value: "crop-1" } });
    await waitFor(() => expect(screen.getByText("Mamutik")).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText(/variety/i), { target: { value: "var-1" } });
    fireEvent.change(screen.getByLabelText(/supplier lot code/i), { target: { value: "RZ-MAM-2026-001" } });
    fireEvent.click(screen.getByRole("button", { name: /save seed lot/i }));

    await waitFor(() => expect(pushMock).toHaveBeenCalledWith("/farms/farm-1/seed-lots/lot-new"));
  });

  it("has one primary save action and no redundant Review step", async () => {
    stubFetch();
    render(withQueryClient(<NewSeedLotPage />));
    await waitFor(() => expect(screen.getByText("Iceberg Lettuce")).toBeInTheDocument());
    expect(screen.queryByRole("button", { name: /review/i })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /save seed lot/i })).toBeInTheDocument();
  });
});
