import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { ProductionSystemCreate } from "@/lib/api/client";

import { ProductionSystemForm } from "./ProductionSystemForm";

describe("ProductionSystemForm", () => {
  it("submits exact backend fields, with description: null when left blank", async () => {
    const onSubmit = vi.fn();
    render(<ProductionSystemForm isSubmitting={false} onCancel={() => {}} onSubmit={onSubmit} />);
    fireEvent.change(screen.getByLabelText("Code"), { target: { value: "nft" } });
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "NFT Leafy Greens" } });
    fireEvent.click(screen.getByRole("button", { name: /create production system/i }));

    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
    const payload = onSubmit.mock.calls[0][0] as ProductionSystemCreate;
    expect(payload).toEqual({ code: "nft", name: "NFT Leafy Greens", description: null });
  });

  it("has no fertigation recipe, climate, or hardware configuration fields", () => {
    render(<ProductionSystemForm isSubmitting={false} onCancel={() => {}} onSubmit={() => {}} />);
    expect(screen.queryByLabelText(/fertigation/i)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/climate/i)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/hardware/i)).not.toBeInTheDocument();
  });

  it("blocks submit when a required field is missing", async () => {
    const onSubmit = vi.fn();
    const { container } = render(<ProductionSystemForm isSubmitting={false} onCancel={() => {}} onSubmit={onSubmit} />);
    fireEvent.submit(container.querySelector("form")!);

    await waitFor(() => expect(screen.getByText("Code is required")).toBeInTheDocument());
    expect(onSubmit).not.toHaveBeenCalled();
  });
});
