import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { CropRead, ProductionSystemRead, WorkflowCreate } from "@/lib/api/client";
import { withQueryClient } from "@/lib/test-utils";

import { WorkflowForm } from "./WorkflowForm";

const crops: CropRead[] = [
  { id: "crop-1", tenant_id: "t", code: "ICE", common_name: "Iceberg Lettuce", scientific_name: null, crop_category: "leafy_green", status: "active" },
];
const productionSystems: ProductionSystemRead[] = [
  { id: "ps-1", tenant_id: "t", code: "NFT", name: "NFT Leafy Greens", description: null, status: "active" },
];
const varieties = [
  { id: "var-1", tenant_id: "t", crop_id: "crop-1", code: "MAM", name: "Mamutik", supplier_reference: null, status: "active" },
];

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

function stubFetch() {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/varieties")) return jsonResponse(varieties);
      return jsonResponse([]);
    }),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("WorkflowForm", () => {
  it("scopes the Variety dropdown to the selected Crop, and clears it when the Crop changes", async () => {
    stubFetch();
    render(
      withQueryClient(
        <WorkflowForm crops={crops} productionSystems={productionSystems} isSubmitting={false} onCancel={() => {}} onSubmit={() => {}} />,
      ),
    );

    const varietySelect = screen.getByLabelText("Variety (optional)") as HTMLSelectElement;
    expect(varietySelect).toBeDisabled();

    fireEvent.change(screen.getByLabelText("Crop"), { target: { value: "crop-1" } });
    await waitFor(() => expect(varietySelect).not.toBeDisabled());
    await waitFor(() => expect(screen.getByRole("option", { name: "Mamutik (MAM)" })).toBeInTheDocument());
  });

  it("submits variety_id: null when no variety is selected -- Variety stays optional", async () => {
    stubFetch();
    const onSubmit = vi.fn();
    render(
      withQueryClient(
        <WorkflowForm crops={crops} productionSystems={productionSystems} isSubmitting={false} onCancel={() => {}} onSubmit={onSubmit} />,
      ),
    );
    fireEvent.change(screen.getByLabelText("Code"), { target: { value: "wf-1" } });
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Workflow 1" } });
    fireEvent.change(screen.getByLabelText("Crop"), { target: { value: "crop-1" } });
    fireEvent.change(screen.getByLabelText("Production system"), { target: { value: "ps-1" } });
    fireEvent.click(screen.getByRole("button", { name: /create workflow draft/i }));

    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
    const payload = onSubmit.mock.calls[0][0] as WorkflowCreate;
    expect(payload).toEqual({ crop_id: "crop-1", variety_id: null, production_system_id: "ps-1", code: "wf-1", name: "Workflow 1" });
  });

  it("blocks submit when Crop or Production System is missing", async () => {
    stubFetch();
    const onSubmit = vi.fn();
    const { container } = render(
      withQueryClient(
        <WorkflowForm crops={crops} productionSystems={productionSystems} isSubmitting={false} onCancel={() => {}} onSubmit={onSubmit} />,
      ),
    );
    fireEvent.change(screen.getByLabelText("Code"), { target: { value: "wf-1" } });
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Workflow 1" } });
    fireEvent.submit(container.querySelector("form")!);

    await waitFor(() => expect(screen.getByText("Select a crop")).toBeInTheDocument());
    expect(onSubmit).not.toHaveBeenCalled();
  });
});
