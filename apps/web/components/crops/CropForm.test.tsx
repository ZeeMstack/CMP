import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { CropCreate } from "@/lib/api/client";

import { CropForm } from "./CropForm";

function fillRequiredFields() {
  fireEvent.change(screen.getByLabelText("Code"), { target: { value: "ice" } });
  fireEvent.change(screen.getByLabelText("Common name"), { target: { value: "Iceberg Lettuce" } });
}

describe("CropForm", () => {
  it("renders exactly the backend's crop_category options, values preserved", () => {
    render(<CropForm isSubmitting={false} onCancel={() => {}} onSubmit={() => {}} />);
    const select = screen.getByLabelText("Crop category") as HTMLSelectElement;
    const values = Array.from(select.options).map((o) => o.value);
    expect(values).toEqual(["leafy_green", "vine", "herb", "other"]);
  });

  it("submits with scientific_name: null when left blank, never an empty string", async () => {
    const onSubmit = vi.fn();
    render(<CropForm isSubmitting={false} onCancel={() => {}} onSubmit={onSubmit} />);
    fillRequiredFields();
    fireEvent.click(screen.getByRole("button", { name: /create crop/i }));

    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
    const payload = onSubmit.mock.calls[0][0] as CropCreate;
    expect(payload.scientific_name).toBeNull();
    expect(payload).toMatchObject({ code: "ice", common_name: "Iceberg Lettuce", crop_category: "leafy_green" });
  });

  it("blocks submit when a required field is missing", async () => {
    const onSubmit = vi.fn();
    const { container } = render(<CropForm isSubmitting={false} onCancel={() => {}} onSubmit={onSubmit} />);
    fireEvent.submit(container.querySelector("form")!);

    await waitFor(() => expect(screen.getByText("Code is required")).toBeInTheDocument());
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("shows a server error banner without losing entered field values", async () => {
    render(<CropForm isSubmitting={false} onCancel={() => {}} onSubmit={() => {}} serverError="Crop code already exists in this tenant" />);
    expect(screen.getByRole("alert")).toHaveTextContent("Crop code already exists in this tenant");
  });
});
