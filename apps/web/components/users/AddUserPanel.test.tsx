import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api/client", () => ({ lookupUserByEmail: vi.fn() }));

import { lookupUserByEmail } from "@/lib/api/client";
import { AppError } from "@/lib/errors/adapter";
import { withQueryClient } from "@/lib/test-utils";
import type { RoleOption } from "@/lib/api/client";

import { AddUserPanel } from "./AddUserPanel";

const ROLES: RoleOption[] = [
  { code: "operator", name: "Operator", description: "Routine farm operations." },
];

describe("AddUserPanel", () => {
  it("shows truthful provisioning guidance -- never implies signing in creates the user", async () => {
    // The component checks `instanceof AppError` -- the mocked rejection
    // must be a real instance, not a plain Error, for that branch to fire.
    vi.mocked(lookupUserByEmail).mockRejectedValue(
      new AppError(
        "not_found",
        "No GrowCMP user exists for this email. The user must first be provisioned by a Platform " +
          "Administrator before they can be added to this tenant.",
      ),
    );

    render(
      withQueryClient(
        <AddUserPanel roles={ROLES} onCancel={vi.fn()} onSubmit={vi.fn()} isSubmitting={false} serverError={null} />,
      ),
    );

    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "nobody@example.com" } });
    fireEvent.click(screen.getByRole("button", { name: "Check" }));

    await waitFor(() => expect(screen.getByText(/Platform Administrator/)).toBeInTheDocument());
    expect(screen.queryByText(/sign in/i)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add User" })).toBeDisabled();
  });

  it("shows the ambiguous-identity message and never enables Add when the email matches more than one user", async () => {
    vi.mocked(lookupUserByEmail).mockRejectedValue(
      new AppError(
        "conflict",
        "More than one GrowCMP identity uses this email. A Platform Administrator must resolve the " +
          "identity before tenant access can be assigned.",
      ),
    );

    render(
      withQueryClient(
        <AddUserPanel roles={ROLES} onCancel={vi.fn()} onSubmit={vi.fn()} isSubmitting={false} serverError={null} />,
      ),
    );

    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "shared@example.com" } });
    fireEvent.click(screen.getByRole("button", { name: "Check" }));

    await waitFor(() => expect(screen.getByText(/More than one GrowCMP identity/)).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Add User" })).toBeDisabled();
  });

  it("enables role selection and Add User once the email resolves to a real user", async () => {
    vi.mocked(lookupUserByEmail).mockResolvedValue({
      id: "u1",
      email: "ali@example.com",
      display_name: "Ali Raza",
    });
    const onSubmit = vi.fn();

    render(
      withQueryClient(
        <AddUserPanel roles={ROLES} onCancel={vi.fn()} onSubmit={onSubmit} isSubmitting={false} serverError={null} />,
      ),
    );

    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "ali@example.com" } });
    fireEvent.click(screen.getByRole("button", { name: "Check" }));

    await waitFor(() => expect(screen.getByText(/Found: Ali Raza/)).toBeInTheDocument());

    const roleInput = screen.getByRole("combobox", { name: "Role" });
    fireEvent.focus(roleInput);
    await waitFor(() => expect(screen.getByText("Operator")).toBeInTheDocument());
    fireEvent.click(screen.getByText("Operator"));

    const addButton = screen.getByRole("button", { name: "Add User" });
    expect(addButton).toBeEnabled();
    fireEvent.click(addButton);
    expect(onSubmit).toHaveBeenCalledWith({ userId: "u1", roleCode: "operator" });
  });
});
