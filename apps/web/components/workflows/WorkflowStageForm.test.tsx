import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { CarrierTypeRead, WorkflowStageCreate } from "@/lib/api/client";

import { WorkflowStageForm } from "./WorkflowStageForm";

const carrierTypes: CarrierTypeRead[] = [
  { id: "ct-1", code: "GROW_CUBE", name: "Grow Cube", requires_specification: false, biological_position_label: null },
];

function fillRequiredFields() {
  fireEvent.change(screen.getByLabelText("Code"), { target: { value: "seeding" } });
  fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Seeding" } });
}

describe("WorkflowStageForm", () => {
  it("renders exactly the backend's STAGE_CATEGORIES options, values preserved", () => {
    render(<WorkflowStageForm carrierTypes={carrierTypes} nextDisplayOrder={0} isSubmitting={false} onCancel={() => {}} onSubmit={() => {}} />);
    const select = screen.getByLabelText("Stage category") as HTMLSelectElement;
    const values = Array.from(select.options).map((o) => o.value);
    expect(values).toEqual([
      "seeding", "germination", "nursery", "transplanting", "intermediate",
      "production", "harvest_ready", "harvesting", "completed", "rejected",
    ]);
  });

  it("defaults display_order to the next free slot", () => {
    render(<WorkflowStageForm carrierTypes={carrierTypes} nextDisplayOrder={3} isSubmitting={false} onCancel={() => {}} onSubmit={() => {}} />);
    expect(screen.getByLabelText("Display order")).toHaveValue(3);
  });

  it("submits is_start/is_terminal accurately, and required_carrier_type_code: null when left unset", async () => {
    const onSubmit = vi.fn();
    render(<WorkflowStageForm carrierTypes={carrierTypes} nextDisplayOrder={0} isSubmitting={false} onCancel={() => {}} onSubmit={onSubmit} />);
    fillRequiredFields();
    fireEvent.click(screen.getByLabelText("Start stage"));
    fireEvent.click(screen.getByRole("button", { name: /add stage/i }));

    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
    const payload = onSubmit.mock.calls[0][0] as WorkflowStageCreate;
    expect(payload.is_start).toBe(true);
    expect(payload.is_terminal).toBe(false);
    expect(payload.required_carrier_type_code).toBeNull();
    expect(payload.permitted_location_type_code).toBeNull();
    expect(payload.expected_duration_minutes).toBeNull();
  });

  it("submits the selected required carrier type code (not its id)", async () => {
    const onSubmit = vi.fn();
    render(<WorkflowStageForm carrierTypes={carrierTypes} nextDisplayOrder={0} isSubmitting={false} onCancel={() => {}} onSubmit={onSubmit} />);
    fillRequiredFields();
    fireEvent.change(screen.getByLabelText("Required carrier type (optional)"), { target: { value: "GROW_CUBE" } });
    fireEvent.click(screen.getByRole("button", { name: /add stage/i }));

    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
    expect((onSubmit.mock.calls[0][0] as WorkflowStageCreate).required_carrier_type_code).toBe("GROW_CUBE");
  });

  it("rejects a zero/negative expected duration", async () => {
    const onSubmit = vi.fn();
    const { container } = render(
      <WorkflowStageForm carrierTypes={carrierTypes} nextDisplayOrder={0} isSubmitting={false} onCancel={() => {}} onSubmit={onSubmit} />,
    );
    fillRequiredFields();
    fireEvent.change(screen.getByLabelText("Expected duration (minutes, optional)"), { target: { value: "0" } });
    fireEvent.submit(container.querySelector("form")!);

    await waitFor(() => expect(screen.getByText("Must be greater than zero")).toBeInTheDocument());
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("has no permitted-location-type selector (no backend list endpoint exists for it)", () => {
    render(<WorkflowStageForm carrierTypes={carrierTypes} nextDisplayOrder={0} isSubmitting={false} onCancel={() => {}} onSubmit={() => {}} />);
    expect(screen.queryByLabelText(/location type/i)).not.toBeInTheDocument();
  });
});
