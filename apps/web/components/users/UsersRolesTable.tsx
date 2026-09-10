"use client";

import { StatusBadge } from "@/components/StatusBadge";
import type { MembershipWithUserRead, RoleOption } from "@/lib/api/client";

/** AUTHZ-OPS-001 section 6/21: the dense Users & Roles table -- name,
 * email, human-readable role, status, one Manage action. No raw UUIDs, no
 * internal Auth0/OIDC identifiers, no permission-constant text. */
export function UsersRolesTable({
  memberships,
  roles,
  currentUserId,
  canManage,
  onManage,
}: {
  memberships: MembershipWithUserRead[];
  roles: RoleOption[];
  currentUserId: string | null;
  /** AUTHZ-OPS-001 section 16: hides the Manage action entirely for a
   * caller whose own role cannot administer memberships -- a frontend
   * courtesy only; the backend's own permission check is authoritative. */
  canManage: boolean;
  onManage: (membership: MembershipWithUserRead) => void;
}) {
  const roleName = (code: string | null) => roles.find((r) => r.code === code)?.name ?? code ?? "—";

  return (
    <div className="overflow-x-auto rounded-xl border border-border-subtle bg-surface">
      <table className="w-full text-left text-sm">
        <thead className="border-b border-border-subtle bg-surface-subtle text-xs uppercase text-ink-muted">
          <tr>
            <th className="px-4 py-2 font-medium">User</th>
            <th className="px-4 py-2 font-medium">Email</th>
            <th className="px-4 py-2 font-medium">Role</th>
            <th className="px-4 py-2 font-medium">Status</th>
            {canManage && <th className="px-4 py-2 font-medium" />}
          </tr>
        </thead>
        <tbody className="divide-y divide-border-subtle">
          {memberships.map((membership) => {
            const isSelf = currentUserId !== null && membership.user_id === currentUserId;
            const isActive = membership.status === "active";
            return (
              <tr key={membership.id} className="hover:bg-surface-subtle">
                <td className="px-4 py-2 font-medium text-ink">
                  {membership.user_display_name}
                  {isSelf && <span className="ml-2 text-xs font-normal text-wl-text-tertiary">(You)</span>}
                </td>
                <td className="px-4 py-2 text-ink-muted">{membership.user_email}</td>
                <td className="px-4 py-2 text-ink-muted">{roleName(membership.role_code)}</td>
                <td className="px-4 py-2">
                  <StatusBadge label={isActive ? "Active" : "Inactive"} tone={isActive ? "active" : "neutral"} />
                </td>
                {canManage && (
                  <td className="px-4 py-2">
                    <button
                      type="button"
                      onClick={() => onManage(membership)}
                      className="text-sm font-medium text-brand-700 hover:underline"
                    >
                      Manage
                    </button>
                  </td>
                )}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
