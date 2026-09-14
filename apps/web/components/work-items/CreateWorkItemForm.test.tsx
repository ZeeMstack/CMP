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
});
