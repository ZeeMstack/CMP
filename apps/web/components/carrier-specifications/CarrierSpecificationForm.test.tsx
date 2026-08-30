import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { CarrierSpecificationCreate, CarrierTypeRead } from "@/lib/api/client";

import { CarrierSpecificationForm } from "./CarrierSpecificationForm";

const carrierTypes: CarrierTypeRead[] = [
  { id: "ct-1", code: "GROW_CUBE", name: "Grow Cube", requires_specification: false, biological_position_label: null },
];

function fillRequiredFields() {
  fireEvent.change(screen.getByLabelText("Carrier type"), { target: { value: "GROW_CUBE" } });
  fireEvent.change(screen.getByLabelText("Code"), { target: { value: "GC1" } });
  fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Grow Cube 1" } });
}

/** FINAL INTEGRITY CLEANUP: regression coverage for the optional-numeric
 * `setValueAs` bug -- react-hook-form routes an untouched field's own
 * `null` default through the same transform used for a real DOM change
 * event, so `Number(null)` (which is `0`, not `NaN`) was previously
 * computed for every optional dimension/position-count field left blank,
 * tripping `.positive()` and silently blocking an otherwise valid submit. */
describe("CarrierSpecificationForm -- optional numeric fields", () => {
  it("submits with height_mm: null when the optional Height field is left blank, never 0", async () => {
    const onSubmit = vi.fn();
    render(<CarrierSpecificationForm carrierTypes={carrierTypes} isSubmitting={false} onCancel={() => {}} onSubmit={onSubmit} />);
    fillRequiredFields();
    fireEvent.click(screen.getByRole("button", { name: /create specification/i }));

    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
    const payload = onSubmit.mock.calls[0][0] as CarrierSpecificationCreate;
    expect(payload.height_mm).toBeNull();
    expect(payload.height_mm).not.toBe(0);
  });

  it("submits successfully with every optional dimension left blank (a valid create is never blocked)", async () => {
    const onSubmit = vi.fn();
    render(<CarrierSpecificationForm carrierTypes={carrierTypes} isSubmitting={false} onCancel={() => {}} onSubmit={onSubmit} />);
    fillRequiredFields();
    fireEvent.click(screen.getByRole("button", { name: /create specification/i }));

    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
    expect(screen.queryByText("Must be greater than zero")).not.toBeInTheDocument();
    const payload = onSubmit.mock.calls[0][0] as CarrierSpecificationCreate;
    expect(payload).toMatchObject({ length_mm: null, width_mm: null, height_mm: null, biological_position_count: null });
  });

  it("submits the real entered value when an optional Height is actually filled in", async () => {
    const onSubmit = vi.fn();
    render(<CarrierSpecificationForm carrierTypes={carrierTypes} isSubmitting={false} onCancel={() => {}} onSubmit={onSubmit} />);
    fillRequiredFields();
    fireEvent.change(screen.getByLabelText("Height (mm, optional)"), { target: { value: "120" } });
    fireEvent.click(screen.getByRole("button", { name: /create specification/i }));

    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
    const payload = onSubmit.mock.calls[0][0] as CarrierSpecificationCreate;
    expect(payload.height_mm).toBe(120);
  });

  it("still rejects an actually-invalid entered numeric value (0 fails the positive check)", async () => {
    const onSubmit = vi.fn();
    const { container } = render(
      <CarrierSpecificationForm carrierTypes={carrierTypes} isSubmitting={false} onCancel={() => {}} onSubmit={onSubmit} />,
    );
    fillRequiredFields();
    fireEvent.change(screen.getByLabelText("Height (mm, optional)"), { target: { value: "0" } });
    // `min`/`step` on this <input type="number"> make 0 fail the browser's
    // OWN native constraint validation (rangeUnderflow) -- a real click on
    // the submit button never even reaches React's submit handler in that
    // case, so this dispatches `submit` directly on the <form> (the
    // standard way to exercise react-hook-form/zod validation independent
    // of native HTML5 constraints, which are enforced identically here and
    // are not what this test is about).
    fireEvent.submit(container.querySelector("form")!);

    await waitFor(() => expect(screen.getByText("Must be greater than zero")).toBeInTheDocument());
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("applies the identical null-safe fix to biological_position_count, with no change to its own semantics", async () => {
    const onSubmit = vi.fn();
    render(<CarrierSpecificationForm carrierTypes={carrierTypes} isSubmitting={false} onCancel={() => {}} onSubmit={onSubmit} />);
    fillRequiredFields();
    fireEvent.click(screen.getByRole("button", { name: /create specification/i }));

    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
    let payload = onSubmit.mock.calls[0][0] as CarrierSpecificationCreate;
    expect(payload.biological_position_count).toBeNull();

    onSubmit.mockClear();
    fireEvent.change(screen.getByLabelText(/Biological positions count|Cells count/i), { target: { value: "48" } });
    fireEvent.click(screen.getByRole("button", { name: /create specification/i }));
    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
    payload = onSubmit.mock.calls[0][0] as CarrierSpecificationCreate;
    expect(payload.biological_position_count).toBe(48);
  });
});
