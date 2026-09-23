import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useParams: () => ({ farmId: "farm-1", seedLotId: "lot-1" }),
}));

import { withQueryClient } from "@/lib/test-utils";

import SeedLotDetailPage from "./page";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const SEED_LOT = {
  id: "lot-1", tenant_id: "t", farm_id: "f", code: "RZ-MAM-2026-001",
  crop: { id: "crop-1", code: "ICE", common_name: "Iceberg Lettuce" },
  variety: { id: "var-1", code: "MAM", name: "Mamutik" },
  supplier_name: "Rijk Zwaan", supplier_lot_reference: "REF-1", received_date: "2026-01-01", expiry_date: "2027-01-01",
  status: "active", created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z",
};

const BATCHES = [{ id: "b1", code: "CB-0001", sown_effective_time: "2026-02-01T09:00:00Z" }];

function stubFetch(overrides: Record<string, unknown> = {}) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/crop-batches")) return jsonResponse(overrides.batches ?? BATCHES);
      if (url.endsWith("/farms/farm-1")) return jsonResponse({ id: "farm-1", timezone: "Asia/Dubai" });
      if (url.includes("/seed-lots/lot-1")) return jsonResponse(overrides.seedLot ?? SEED_LOT);
      return jsonResponse([]);
    }),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("SeedLotDetailPage: compact facts plus bounded linked-batch activity", () => {
  it("shows compact identity/provenance facts", async () => {
    stubFetch();
    render(withQueryClient(<SeedLotDetailPage />));
    await waitFor(() => expect(screen.getByRole("heading", { name: "RZ-MAM-2026-001" })).toBeInTheDocument());
    expect(screen.getByText("Iceberg Lettuce")).toBeInTheDocument();
    expect(screen.getByText("Mamutik")).toBeInTheDocument();
    expect(screen.getByText("Rijk Zwaan")).toBeInTheDocument();
  });

  it("shows linked Crop Batches in a bounded region", async () => {
    stubFetch();
    render(withQueryClient(<SeedLotDetailPage />));
    await waitFor(() => expect(screen.getByRole("region", { name: "Linked Crop Batches" })).toBeInTheDocument());
    expect(screen.getByRole("link", { name: /CB-0001/ })).toHaveAttribute("href", "/farms/farm-1/crop-batches/b1");
  });

  it("shows an empty state when no Batches have been sown from this Seed Lot", async () => {
    stubFetch({ batches: [] });
    render(withQueryClient(<SeedLotDetailPage />));
    await waitFor(() => expect(screen.getByText("No Crop Batches sown from this Seed Lot yet.")).toBeInTheDocument());
  });
});
