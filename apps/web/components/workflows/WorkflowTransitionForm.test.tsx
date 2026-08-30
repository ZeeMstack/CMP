import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { WorkflowStageRead, WorkflowTransitionCreate } from "@/lib/api/client";

import { WorkflowTransitionForm } from "./WorkflowTransitionForm";

const stages: WorkflowStageRead[] = [
  {
    id: "stage-1", tenant_id: "t", workflow_version_id: "v1", code: "SEEDING", name: "Seeding",
    display_order: 0, stage_category: "seeding", expected_duration_minutes: null,
    permitted_location_type_id: null, required_carrier_type_id: null, is_start: true, is_terminal: false,
  },
  {
    id: "stage-2", tenant_id: "t", workflow_version_id: "v1", code: "GERMINATION", name: "Germination",
    display_order: 1, stage_category: "germination", expected_duration_minutes: null,
    permitted_location_type_id: null, required_carrier_type_id: null, is_start: false, is_terminal: true,
  },
];

describe("WorkflowTransitionForm", () => {
  it("only offers this draft version's own existing stages, never a typed id", () => {
    render(<WorkflowTransitionForm stages={stages} isSubmitting={false} onCancel={() => {}} onSubmit={() => {}} />);
    const fromSelect = screen.getByLabelText("From stage") as HTMLSelectElement;
    const values = Array.from(fromSelect.options).map((o) => o.value).filter(Boolean);
    expect(values).toEqual(["stage-1", "stage-2"]);
  });

  it("submits the selected from/to stage ids and code/name", async () => {
    const onSubmit = vi.fn();
    render(<WorkflowTransitionForm stages={stages} isSubmitting={false} onCancel={() => {}} onSubmit={onSubmit} />);
    fireEvent.change(screen.getByLabelText("From stage"), { target: { value: "stage-1" } });
    fireEvent.change(screen.getByLabelText("To stage"), { target: { value: "stage-2" } });
    fireEvent.change(screen.getByLabelText("Code"), { target: { value: "TO_GERM" } });
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Move to Germination" } });
    fireEvent.click(screen.getByRole("button", { name: /add transition/i }));

    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
    const payload = onSubmit.mock.calls[0][0] as WorkflowTransitionCreate;
    expect(payload).toEqual({ from_stage_id: "stage-1", to_stage_id: "stage-2", code: "TO_GERM", name: "Move to Germination" });
  });

  it("blocks an identical from/to stage selection client-side", async () => {
    const onSubmit = vi.fn();
    const { container } = render(
      <WorkflowTransitionForm stages={stages} isSubmitting={false} onCancel={() => {}} onSubmit={onSubmit} />,
    );
    fireEvent.change(screen.getByLabelText("From stage"), { target: { value: "stage-1" } });
    fireEvent.change(screen.getByLabelText("To stage"), { target: { value: "stage-1" } });
    fireEvent.change(screen.getByLabelText("Code"), { target: { value: "SELF" } });
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Self" } });
    fireEvent.submit(container.querySelector("form")!);

    await waitFor(() => expect(screen.getByText("A stage cannot transition to itself")).toBeInTheDocument());
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("disables Add transition when fewer than two stages exist", () => {
    render(<WorkflowTransitionForm stages={[stages[0]]} isSubmitting={false} onCancel={() => {}} onSubmit={() => {}} />);
    expect(screen.getByRole("button", { name: /add transition/i })).toBeDisabled();
  });
});
