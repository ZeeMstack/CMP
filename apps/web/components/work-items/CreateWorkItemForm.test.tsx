import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { CreateWorkItemForm } from "./CreateWorkItemForm";

describe("CreateWorkItemForm", () => {
  it("rejects submission with a blank title/work type", async () => {
    const onSubmit = vi.fn();
    render(<CreateWorkItemForm onSubmit={onSubmit} onCancel={vi.fn()} isSubmitting={false} />);

    fireEvent.click(screen.getByRole("button", { name: "Create work item" }));

    expect(await screen.findByText("Title is required")).toBeInTheDocument();
    expect(await screen.findByText("Work type is required")).toBeInTheDocument();
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("submits a manual_record payload with the filled-in fields", async () => {
    const onSubmit = vi.fn();
    render(<CreateWorkItemForm onSubmit={onSubmit} onCancel={vi.fn()} isSubmitting={false} currentUserId="me" />);

    fireEvent.change(screen.getByPlaceholderText("Clean Germination Trolley 03"), {
      target: { value: "Inspect GH-01 cooling pad" },
    });
    fireEvent.change(screen.getByPlaceholderText("cleaning"), { target: { value: "inspection" } });
    fireEvent.click(screen.getByLabelText("Assign to me"));
    fireEvent.click(screen.getByRole("button", { name: "Create work item" }));

    expect(await screen.findByRole("button", { name: "Create work item" })).toBeInTheDocument();
    expect(onSubmit).toHaveBeenCalledTimes(1);
    const payload = onSubmit.mock.calls[0][0];
    expect(payload).toMatchObject({
      work_type: "inspection",
      title: "Inspect GH-01 cooling pad",
      category: "maintenance",
      priority: "normal",
      completion_mode: "manual_record",
      assigned_to_user_id: "me",
    });
    expect(typeof payload.client_command_id).toBe("string");
  });

  it("the Assign-to-me checkbox is disabled with no known current user", () => {
    render(<CreateWorkItemForm onSubmit={vi.fn()} onCancel={vi.fn()} isSubmitting={false} />);
    expect(screen.getByLabelText("Assign to me")).toBeDisabled();
  });

  it("context selects are hidden by default and appear behind 'Add context'", () => {
    render(
      <CreateWorkItemForm
        onSubmit={vi.fn()}
        onCancel={vi.fn()}
        isSubmitting={false}
        locationOptions={[{ id: "loc-1", label: "GH-01 cooling pad" }]}
      />,
    );
    expect(screen.queryByLabelText("Location")).not.toBeInTheDocument();
    fireEvent.click(screen.getByText("+ Add context (location, batch, asset, carrier)"));
    expect(screen.getByLabelText("Location")).toBeInTheDocument();
  });

  it("submits with the selected Location's real id, never a display string", async () => {
    const onSubmit = vi.fn();
    render(
      <CreateWorkItemForm
        onSubmit={onSubmit}
        onCancel={vi.fn()}
        isSubmitting={false}
        locationOptions={[{ id: "loc-uuid-1", label: "GH-01 cooling pad" }]}
      />,
    );
    fireEvent.change(screen.getByPlaceholderText("Clean Germination Trolley 03"), {
      target: { value: "Inspect GH-01 cooling pad" },
    });
    fireEvent.change(screen.getByPlaceholderText("cleaning"), { target: { value: "inspection" } });
    fireEvent.click(screen.getByText("+ Add context (location, batch, asset, carrier)"));
    fireEvent.change(screen.getByLabelText("Location"), { target: { value: "loc-uuid-1" } });
    fireEvent.click(screen.getByRole("button", { name: "Create work item" }));

    await screen.findByRole("button", { name: "Create work item" });
    expect(onSubmit).toHaveBeenCalledTimes(1);
    const payload = onSubmit.mock.calls[0][0];
    expect(payload.location_id).toBe("loc-uuid-1");
    expect(payload.crop_batch_id).toBeNull();
  });

  it("submits with the selected Batch's real id", async () => {
    const onSubmit = vi.fn();
    render(
      <CreateWorkItemForm
        onSubmit={onSubmit}
        onCancel={vi.fn()}
        isSubmitting={false}
        batchOptions={[{ id: "batch-uuid-1", label: "B-LET-2026-014 · Lettuce" }]}
      />,
    );
    fireEvent.change(screen.getByPlaceholderText("Clean Germination Trolley 03"), {
      target: { value: "Check Batch after transfer" },
    });
    fireEvent.change(screen.getByPlaceholderText("cleaning"), { target: { value: "inspection" } });
    fireEvent.click(screen.getByText("+ Add context (location, batch, asset, carrier)"));
    fireEvent.change(screen.getByLabelText("Batch"), { target: { value: "batch-uuid-1" } });
    fireEvent.click(screen.getByRole("button", { name: "Create work item" }));

    await screen.findByRole("button", { name: "Create work item" });
    expect(onSubmit).toHaveBeenCalledTimes(1);
    expect(onSubmit.mock.calls[0][0].crop_batch_id).toBe("batch-uuid-1");
  });

  it("omitted context fields are submitted as null, never an empty string placeholder", async () => {
    const onSubmit = vi.fn();
    render(<CreateWorkItemForm onSubmit={onSubmit} onCancel={vi.fn()} isSubmitting={false} />);
    fireEvent.change(screen.getByPlaceholderText("Clean Germination Trolley 03"), { target: { value: "Clean" } });
    fireEvent.change(screen.getByPlaceholderText("cleaning"), { target: { value: "cleaning" } });
    fireEvent.click(screen.getByRole("button", { name: "Create work item" }));

    await screen.findByRole("button", { name: "Create work item" });
    const payload = onSubmit.mock.calls[0][0];
    expect(payload.location_id).toBeNull();
    expect(payload.crop_batch_id).toBeNull();
    expect(payload.asset_id).toBeNull();
    expect(payload.carrier_id).toBeNull();
  });

  // PILOT-AGRO-001B: "Assign corrective work" from a Crop Issue reuses this
  // exact existing form, never a second agronomy task model.
  it("with lockedCropIssue, submits crop_issue_id and its Batch without an editable Batch picker", async () => {
    const onSubmit = vi.fn();
    render(
      <CreateWorkItemForm
        onSubmit={onSubmit}
        onCancel={vi.fn()}
        isSubmitting={false}
        lockedCropIssue={{ id: "issue-uuid-1", code: "CI-20260101-0001", batchId: "batch-uuid-1", batchLabel: "B-LET-2026-014" }}
      />,
    );
    expect(screen.getByText("CI-20260101-0001", { exact: false })).toBeInTheDocument();
    fireEvent.change(screen.getByPlaceholderText("Clean Germination Trolley 03"), {
      target: { value: "Prune affected plants" },
    });
    fireEvent.change(screen.getByPlaceholderText("cleaning"), { target: { value: "crop_care" } });
    fireEvent.click(screen.getByRole("button", { name: "Create work item" }));

    await screen.findByRole("button", { name: "Create work item" });
    expect(onSubmit).toHaveBeenCalledTimes(1);
    const payload = onSubmit.mock.calls[0][0];
    expect(payload.crop_issue_id).toBe("issue-uuid-1");
    expect(payload.crop_batch_id).toBe("batch-uuid-1");

    fireEvent.click(screen.getByText("+ Add context (location, batch, asset, carrier)"));
    expect(screen.queryByLabelText("Batch")).not.toBeInTheDocument();
  });
});
