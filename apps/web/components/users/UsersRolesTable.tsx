"use client";

import { StatusBadge } from "@/components/StatusBadge";
import { Button } from "@/components/ui/Button";
import {
  tableBodyDividerClass,
  tableHeadRowClass,
  tableRowHoverClass,
  tableTdClass,
  tableThClass,
  tableWrapperClass,
} from "@/components/ui/table";
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
    <div className={tableWrapperClass}>
      <table className="w-full text-left text-sm">
        <thead>
          <tr className={tableHeadRowClass}>
            <th className={tableThClass}>User</th>
            <th className={tableThClass}>Email</th>
            <th className={tableThClass}>Role</th>
            <th className={tableThClass}>Status</th>
            {canManage && <th className={tableThClass} />}
          </tr>
        </thead>
        <tbody className={tableBodyDividerClass}>
          {memberships.map((membership) => {
            const isSelf = currentUserId !== null && membership.user_id === currentUserId;
            const isActive = membership.status === "active";
            return (
              <tr key={membership.id} className={tableRowHoverClass}>
                <td className={`${tableTdClass} font-medium text-wl-text`}>
                  {membership.user_display_name}
                  {isSelf && <span className="ml-2 text-xs font-normal text-wl-text-tertiary">(You)</span>}
                </td>
                <td className={`${tableTdClass} text-wl-text-secondary`}>{membership.user_email}</td>
                <td className={`${tableTdClass} text-wl-text-secondary`}>{roleName(membership.role_code)}</td>
                <td className={tableTdClass}>
                  <StatusBadge label={isActive ? "Active" : "Inactive"} tone={isActive ? "active" : "neutral"} />
                </td>
                {canManage && (
                  <td className={`${tableTdClass} py-1.5 text-right`}>
                    <Button variant="secondary" onClick={() => onManage(membership)}>
                      Manage
                    </Button>
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
