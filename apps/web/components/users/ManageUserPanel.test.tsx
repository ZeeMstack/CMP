import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { MembershipWithUserRead, RoleOption } from "@/lib/api/client";

import { ManageUserPanel } from "./ManageUserPanel";

const ROLES: RoleOption[] = [
  { code: "operator", name: "Operator", description: "Routine farm operations." },
  { code: "qc_officer", name: "Quality Officer", description: "Quality inspection and disposition operations." },
];

const MEMBERSHIP: MembershipWithUserRead = {
  id: "m1",
  user_id: "u1",
  status: "active",
  role_code: "operator",
  user_email: "sara@example.com",
  user_display_name: "Sara Khan",
};

function renderPanel(overrides: Partial<Parameters<typeof ManageUserPanel>[0]> = {}) {
  const onSaveRole = vi.fn();
  const onDeactivate = vi.fn();
  const props = {
    membership: MEMBERSHIP,
    roles: ROLES,
    isSelf: false,
    isLastActiveTenantAdmin: false,
    onClose: vi.fn(),
    onSaveRole,
    onDeactivate,
    onReactivate: vi.fn(),
    isSavingRole: false,
    isDeactivating: false,
    isReactivating: false,
    serverError: null,
    ...overrides,
  };
  render(<ManageUserPanel {...props} />);
  return { onSaveRole, onDeactivate };
}

describe("ManageUserPanel", () => {
  it("shows the role description and saves the newly selected role", async () => {
    const { onSaveRole } = renderPanel();

    expect(screen.getByText("Routine farm operations.")).toBeInTheDocument();

    const roleInput = screen.getByRole("combobox", { name: "Role" });
    fireEvent.focus(roleInput);
    await waitFor(() => expect(screen.getByText("Quality Officer")).toBeInTheDocument());
    fireEvent.click(screen.getByText("Quality Officer"));

    expect(screen.getByText("Quality inspection and disposition operations.")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Save Changes" }));
    expect(onSaveRole).toHaveBeenCalledWith("qc_officer");
  });

  it("requires confirmation before deactivating access", () => {
    const { onDeactivate } = renderPanel();

    fireEvent.click(screen.getByRole("button", { name: "Deactivate Access" }));
    expect(screen.getByText(/Deactivate access for Sara Khan\?/)).toBeInTheDocument();
    expect(onDeactivate).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Deactivate" }));
    expect(onDeactivate).toHaveBeenCalled();
  });

  it("disables Deactivate when this is the last active Tenant Admin", () => {
    renderPanel({ isLastActiveTenantAdmin: true });
    expect(screen.getByRole("button", { name: "Deactivate Access" })).toBeDisabled();
    expect(screen.getByText(/only active Tenant Admin/)).toBeInTheDocument();
  });
});
