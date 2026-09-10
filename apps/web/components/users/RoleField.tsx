"use client";

import { FilterableSelect } from "@/components/FilterableSelect";
import type { RoleOption } from "@/lib/api/client";

/** AUTHZ-OPS-001: the one role picker shared by Add User and Manage User --
 * a searchable select (reusing the existing FilterableSelect primitive,
 * NURSERY-OPS-004B.2) plus a persistent description line beneath it, so the
 * chosen role's meaning stays visible even after the dropdown closes
 * (ticket section 5/24: "Role explanation shown beneath selection"). The
 * role list itself always comes from the backend's own `GET
 * /memberships/roles` catalog -- never a frontend-invented list -- and the
 * description is explanatory copy only, never consulted for authorization. */
export function RoleField({
  roles,
  value,
  onChange,
  disabled,
}: {
  roles: RoleOption[];
  value: string;
  onChange: (roleCode: string) => void;
  disabled?: boolean;
}) {
  const selected = roles.find((r) => r.code === value) ?? null;

  return (
    <div className="flex flex-col gap-1.5">
      <label className="text-xs font-medium uppercase tracking-wide text-wl-text-tertiary">Role</label>
      <FilterableSelect
        options={roles.map((r) => ({ value: r.code, label: r.name, description: r.description }))}
        value={value}
        onChange={onChange}
        placeholder="Select a role…"
        disabled={disabled}
        aria-label="Role"
      />
      {selected && <p className="text-xs text-wl-text-secondary">{selected.description}</p>}
    </div>
  );
}
