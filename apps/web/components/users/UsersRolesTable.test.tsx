import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { MembershipWithUserRead, RoleOption } from "@/lib/api/client";

import { UsersRolesTable } from "./UsersRolesTable";

const ROLES: RoleOption[] = [
  { code: "tenant_admin", name: "Tenant Admin", description: "Tenant configuration and user administration." },
  { code: "operator", name: "Operator", description: "Routine farm operations." },
];

const MEMBERSHIPS: MembershipWithUserRead[] = [
  {
    id: "m1",
    user_id: "u1",
    status: "active",
    role_code: "operator",
    user_email: "ali@example.com",
    user_display_name: "Ali Raza",
  },
  {
    id: "m2",
    user_id: "u2",
    status: "removed",
    role_code: "tenant_admin",
    user_email: "zee@example.com",
    user_display_name: "Zeeshan",
  },
];

describe("UsersRolesTable", () => {
  it("renders friendly role names, status, and no raw role codes or ids", () => {
    render(
      <UsersRolesTable memberships={MEMBERSHIPS} roles={ROLES} currentUserId="u2" canManage onManage={vi.fn()} />,
    );

    expect(screen.getByText("Ali Raza")).toBeInTheDocument();
    expect(screen.getByText("ali@example.com")).toBeInTheDocument();
    expect(screen.getByText("Operator")).toBeInTheDocument();
    expect(screen.getByText("Active")).toBeInTheDocument();
    expect(screen.getByText("Inactive")).toBeInTheDocument();
    // The signed-in user's own row is marked.
    expect(screen.getByText("(You)")).toBeInTheDocument();
    // Never a raw role code or membership/user UUID rendered as text.
    expect(screen.queryByText("operator", { exact: true })).not.toBeInTheDocument();
    expect(screen.queryByText("m1")).not.toBeInTheDocument();
    expect(screen.queryByText("u1")).not.toBeInTheDocument();
  });

  it("hides the Manage action entirely when the caller cannot administer memberships", () => {
    render(
      <UsersRolesTable
        memberships={MEMBERSHIPS}
        roles={ROLES}
        currentUserId={null}
        canManage={false}
        onManage={vi.fn()}
      />,
    );
    expect(screen.queryByRole("button", { name: "Manage" })).not.toBeInTheDocument();
  });
});
