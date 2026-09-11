"use client";

import { useState } from "react";

import { RoleField } from "@/components/users/RoleField";
import { Button } from "@/components/ui/Button";
import { StatusBadge } from "@/components/StatusBadge";
import type { MembershipWithUserRead, RoleOption } from "@/lib/api/client";

/** AUTHZ-OPS-001 section 9/24/25/26: the compact "Manage User" panel --
 * role change, deactivate/reactivate. The backend remains the sole
 * authority on the last-active-Tenant-Admin protection (ticket section 11)
 * -- this panel only disables the obvious self-inflicted case (this is the
 * only active Tenant Admin row visible in the table) as a courtesy; the
 * server-side check is what actually prevents it, and its error message is
 * shown verbatim on rejection either way. */
export function ManageUserPanel({
  membership,
  roles,
  isSelf,
  isLastActiveTenantAdmin,
  onClose,
  onSaveRole,
  onDeactivate,
  onReactivate,
  isSavingRole,
  isDeactivating,
  isReactivating,
  serverError,
}: {
  membership: MembershipWithUserRead;
  roles: RoleOption[];
  isSelf: boolean;
  isLastActiveTenantAdmin: boolean;
  onClose: () => void;
  onSaveRole: (roleCode: string) => void;
  onDeactivate: () => void;
  onReactivate: () => void;
  isSavingRole: boolean;
  isDeactivating: boolean;
  isReactivating: boolean;
  serverError: string | null;
}) {
  const [roleCode, setRoleCode] = useState(membership.role_code ?? "");
  const [confirmingDeactivate, setConfirmingDeactivate] = useState(false);

  const roleChanged = roleCode !== (membership.role_code ?? "");
  const isActive = membership.status === "active";
  const deactivateBlocked = isLastActiveTenantAdmin;

  return (
    <div className="mb-6 flex flex-col gap-4 rounded-xl border border-wl-border bg-wl-surface-raised p-5">
      <div className="flex items-start justify-between gap-2">
        <div>
          <h2 className="text-sm font-semibold text-wl-text">
            {membership.user_display_name}
            {isSelf && <span className="ml-2 text-xs font-normal text-wl-text-tertiary">(You)</span>}
          </h2>
          <p className="text-xs text-wl-text-secondary">{membership.user_email}</p>
        </div>
        <StatusBadge label={isActive ? "Active" : "Inactive"} tone={isActive ? "active" : "neutral"} />
      </div>

      <RoleField roles={roles} value={roleCode} onChange={setRoleCode} />

      {deactivateBlocked && (
        <p className="text-xs text-wl-text-tertiary">
          This is the only active Tenant Admin -- role and access changes that would remove the last Tenant Admin
          are not allowed.
        </p>
      )}

      {serverError && <p className="text-sm text-danger-700">{serverError}</p>}

      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          {isActive && !confirmingDeactivate && (
            <Button variant="secondary" onClick={() => setConfirmingDeactivate(true)} disabled={deactivateBlocked}>
              Deactivate Access
            </Button>
          )}
          {isActive && confirmingDeactivate && (
            <div className="flex flex-col gap-2 border-t border-wl-border pt-3">
              <p className="text-sm text-wl-text">
                Deactivate access for {membership.user_display_name}? They will no longer be able to access this
                tenant.
              </p>
              <div className="flex gap-2">
                <Button variant="secondary" onClick={() => setConfirmingDeactivate(false)}>
                  Cancel
                </Button>
                <Button variant="danger" onClick={onDeactivate} disabled={isDeactivating}>
                  {isDeactivating ? "Deactivating…" : "Deactivate"}
                </Button>
              </div>
            </div>
          )}
          {!isActive && (
            <Button variant="secondary" onClick={onReactivate} disabled={isReactivating}>
              {isReactivating ? "Reactivating…" : "Reactivate Access"}
            </Button>
          )}
        </div>

        <div className="flex gap-2">
          <Button variant="secondary" onClick={onClose}>
            Close
          </Button>
          <Button
            variant="primary"
            onClick={() => onSaveRole(roleCode)}
            disabled={!roleChanged || isSavingRole}
          >
            {isSavingRole ? "Saving…" : "Save Changes"}
          </Button>
        </div>
      </div>
    </div>
  );
}
