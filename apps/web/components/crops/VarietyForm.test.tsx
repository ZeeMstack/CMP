import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { VarietyCreate } from "@/lib/api/client";

import { VarietyForm } from "./VarietyForm";

describe("VarietyForm", () => {
  it("submits with supplier_reference: null when left blank -- it stays optional, never required", async () => {
    const onSubmit = vi.fn();
    render(<VarietyForm isSubmitting={false} onCancel={() => {}} onSubmit={onSubmit} />);
    fireEvent.change(screen.getByLabelText("Code"), { target: { value: "mam" } });
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Mamutik" } });
    fireEvent.click(screen.getByRole("button", { name: /create variety/i }));

    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
    const payload = onSubmit.mock.calls[0][0] as VarietyCreate;
    expect(payload).toEqual({ code: "mam", name: "Mamutik", supplier_reference: null });
  });

  it("submits the entered supplier reference when provided", async () => {
    const onSubmit = vi.fn();
    render(<VarietyForm isSubmitting={false} onCancel={() => {}} onSubmit={onSubmit} />);
    fireEvent.change(screen.getByLabelText("Code"), { target: { value: "mam" } });
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Mamutik" } });
    fireEvent.change(screen.getByLabelText("Supplier reference (optional)"), { target: { value: "SUP-001" } });
    fireEvent.click(screen.getByRole("button", { name: /create variety/i }));

    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
    expect((onSubmit.mock.calls[0][0] as VarietyCreate).supplier_reference).toBe("SUP-001");
  });

  it("has no Seed Lot fields (quantity, germination %, price, batch)", () => {
    render(<VarietyForm isSubmitting={false} onCancel={() => {}} onSubmit={() => {}} />);
    expect(screen.queryByLabelText(/quantity/i)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/germination/i)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/price/i)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/batch/i)).not.toBeInTheDocument();
  });

  it("blocks submit when a required field is missing", async () => {
    const onSubmit = vi.fn();
    const { container } = render(<VarietyForm isSubmitting={false} onCancel={() => {}} onSubmit={onSubmit} />);
    fireEvent.submit(container.querySelector("form")!);

    await waitFor(() => expect(screen.getByText("Code is required")).toBeInTheDocument());
    expect(onSubmit).not.toHaveBeenCalled();
  });
});
