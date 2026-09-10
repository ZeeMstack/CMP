import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { withQueryClient } from "@/lib/test-utils";

import { RequirementForm } from "./RequirementForm";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const CROPS = [{ id: "crop-1", code: "ICE", common_name: "Iceberg Lettuce" }];
const VARIETIES = [{ id: "var-1", code: "PANG", name: "Pangkor" }];
const UOMS = [
  { id: "uom-kg", code: "kg", name: "Kilogram", quantity_kind: "mass" },
  { id: "uom-seed", code: "SEED", name: "Seed", quantity_kind: "count" },
];

function stubFetch() {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/varieties")) return jsonResponse(VARIETIES);
      if (url.includes("/crops")) return jsonResponse(CROPS);
      if (url.includes("/uoms")) return jsonResponse(UOMS);
      return jsonResponse([]);
    }),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("RequirementForm", () => {
  it("submits a compact create payload with the entered crop/variety/date/quantity/unit", async () => {
    stubFetch();
    const onSubmit = vi.fn();
    render(withQueryClient(<RequirementForm onSubmit={onSubmit} isSubmitting={false} />));

    await waitFor(() => expect(screen.getByText("Iceberg Lettuce")).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText(/^crop$/i), { target: { value: "crop-1" } });
    await waitFor(() => expect(screen.getByText("Pangkor")).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText(/variety/i), { target: { value: "var-1" } });
    fireEvent.change(screen.getByLabelText(/required by/i), { target: { value: "2026-10-15" } });
    fireEvent.change(screen.getByLabelText(/^quantity$/i), { target: { value: "30000" } });
    fireEvent.change(screen.getByLabelText(/^unit$/i), { target: { value: "uom-kg" } });
    fireEvent.click(screen.getByRole("button", { name: /create requirement/i }));

    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
    const payload = onSubmit.mock.calls[0][0];
    expect(payload).toMatchObject({
      crop_id: "crop-1", variety_id: "var-1", required_by_date: "2026-10-15",
      required_quantity: "30000", quantity_uom_id: "uom-kg",
    });
    expect(payload.client_command_id).toBeTruthy();
  });

  it("shows a server error and keeps the entered values visible rather than clearing the form", async () => {
    stubFetch();
    render(
      withQueryClient(
        <RequirementForm onSubmit={vi.fn()} isSubmitting={false} serverError="A requirement with that code already exists." />,
      ),
    );

    await waitFor(() => expect(screen.getByText("Iceberg Lettuce")).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText(/^crop$/i), { target: { value: "crop-1" } });
    fireEvent.change(screen.getByLabelText(/^quantity$/i), { target: { value: "30000" } });

    expect(screen.getByRole("alert")).toHaveTextContent("A requirement with that code already exists.");
    expect(screen.getByLabelText(/^crop$/i)).toHaveValue("crop-1");
    expect(screen.getByLabelText(/^quantity$/i)).toHaveValue("30000");
  });

  it("requires a crop before allowing variety selection, and never fabricates a variety list", async () => {
    stubFetch();
    render(withQueryClient(<RequirementForm onSubmit={vi.fn()} isSubmitting={false} />));

    await waitFor(() => expect(screen.getByText("Iceberg Lettuce")).toBeInTheDocument());
    expect(screen.getByLabelText(/variety/i)).toBeDisabled();
  });
});
