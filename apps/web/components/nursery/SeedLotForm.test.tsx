import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { withQueryClient } from "@/lib/test-utils";

import { SeedLotForm } from "./SeedLotForm";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const CROPS = [{ id: "crop-1", tenant_id: "t", code: "ICE", common_name: "Iceberg Lettuce", scientific_name: null, crop_category: "leafy_green", status: "active" }];
const VARIETIES = [{ id: "var-1", tenant_id: "t", crop_id: "crop-1", code: "MAM", name: "Mamutik", supplier_reference: null, status: "active" }];

function stubFetch() {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/api/crops/crop-1/varieties")) return jsonResponse(VARIETIES);
      if (url.includes("/api/crops")) return jsonResponse(CROPS);
      return jsonResponse([]);
    }),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("SeedLotForm", () => {
  it("makes clear this is a traceability source, not stock on hand", async () => {
    stubFetch();
    render(withQueryClient(<SeedLotForm onSubmit={vi.fn()} isSubmitting={false} />));
    expect(await screen.findByText(/traceability source/i)).toBeInTheDocument();
    expect(screen.queryByText(/stock on hand/i)).not.toBeInTheDocument();
  });

  it("populates varieties only after a crop is selected", async () => {
    stubFetch();
    render(withQueryClient(<SeedLotForm onSubmit={vi.fn()} isSubmitting={false} />));

    await waitFor(() => expect(screen.getByText("Iceberg Lettuce")).toBeInTheDocument());
    expect(screen.getByLabelText(/variety/i)).toBeDisabled();

    fireEvent.change(screen.getByLabelText(/^crop$/i), { target: { value: "crop-1" } });
    await waitFor(() => expect(screen.getByText("Mamutik")).toBeInTheDocument());
    expect(screen.getByLabelText(/variety/i)).not.toBeDisabled();
  });

  it("submits the built payload with nulled-out blank optional fields", async () => {
    stubFetch();
    const onSubmit = vi.fn();
    render(withQueryClient(<SeedLotForm onSubmit={onSubmit} isSubmitting={false} />));

    await waitFor(() => expect(screen.getByText("Iceberg Lettuce")).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText(/^crop$/i), { target: { value: "crop-1" } });
    await waitFor(() => expect(screen.getByText("Mamutik")).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText(/variety/i), { target: { value: "var-1" } });
    fireEvent.change(screen.getByLabelText(/supplier lot code/i), { target: { value: "RZ-MAM-2026-001" } });
    fireEvent.click(screen.getByRole("button", { name: /save seed lot/i }));

    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
    expect(onSubmit.mock.calls[0][0]).toEqual({
      crop_id: "crop-1", variety_id: "var-1", code: "RZ-MAM-2026-001",
      supplier_name: null, supplier_lot_reference: null, received_date: null, expiry_date: null,
    });
  });

  it("shows a server error", async () => {
    stubFetch();
    render(withQueryClient(<SeedLotForm onSubmit={vi.fn()} isSubmitting={false} serverError="Supplier lot code already exists" />));
    expect(await screen.findByRole("alert")).toHaveTextContent(/already exists/i);
  });
});
