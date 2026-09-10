"use client";

import { PlusCircle } from "lucide-react";
import { useMemo, useState } from "react";

import { AddUserPanel } from "@/components/users/AddUserPanel";
import { Breadcrumbs } from "@/components/Breadcrumbs";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { LoadingSkeleton } from "@/components/LoadingSkeleton";
import { ManageUserPanel } from "@/components/users/ManageUserPanel";
import { PageHeader } from "@/components/PageHeader";
import { StandaloneShell } from "@/components/StandaloneShell";
import { Button } from "@/components/ui/Button";
import { UsersRolesTable } from "@/components/users/UsersRolesTable";
import type { MembershipWithUserRead } from "@/lib/api/client";
import { useAuthBootstrap } from "@/lib/auth/AuthBootstrapProvider";
import { AppError } from "@/lib/errors/adapter";
import {
  useAssignableRoles,
  useChangeMembershipRole,
  useCreateMembership,
  useDeactivateMembership,
  useMemberships,
  useReactivateMembership,
} from "@/lib/query/hooks";

function errorMessage(error: unknown): string {
  return error instanceof AppError ? error.message : "Something went wrong. Please try again.";
}

/** AUTHZ-OPS-001: tenant-scoped Users & Roles administration -- compact
 * table plus inline Add/Manage panels (mirrors GradeDefinitions/Crops'
 * established list+inline-form convention, PILOT-UX-001 compactness).
 * Tenant-wide, not farm-scoped (ticket section 14 -- current roles are
 * tenant-wide; this does not invent farm-scoped access), so it lives
 * outside the /farms/[farmId] tree exactly like Crops/Workflows/Carrier
 * Specifications. Administration controls (Add User, Manage) are hidden
 * for a caller whose own role is not tenant_admin -- a frontend courtesy
 * only (ticket section 16); the backend's own `TENANT_MEMBERS_READ`/
 * `TENANT_MEMBERS_MANAGE` checks are what actually enforce this, and a
 * non-admin's GET /memberships call itself 403s, which the ErrorState
 * below renders cleanly rather than attempting any new authorization UX. */
export default function UsersRolesPage() {
  const { bootstrap } = useAuthBootstrap();
  const isTenantAdmin = bootstrap?.selectedTenantId
    ? bootstrap.memberships.find((m) => m.tenantId === bootstrap.selectedTenantId)?.roleCode === "tenant_admin"
    : false;

  const [search, setSearch] = useState("");
  const [adding, setAdding] = useState(false);
  const [managingId, setManagingId] = useState<string | null>(null);
  const [addError, setAddError] = useState<string | null>(null);
  const [manageError, setManageError] = useState<string | null>(null);

  const membershipsQuery = useMemberships();
  const rolesQuery = useAssignableRoles();
  const createMutation = useCreateMembership();
  const changeRoleMutation = useChangeMembershipRole();
  const deactivateMutation = useDeactivateMembership();
  const reactivateMutation = useReactivateMembership();

  const memberships = useMemo(() => membershipsQuery.data ?? [], [membershipsQuery.data]);
  const roles = useMemo(() => rolesQuery.data ?? [], [rolesQuery.data]);
  const isLoading = membershipsQuery.isLoading || rolesQuery.isLoading;
  const loadError = membershipsQuery.error ?? rolesQuery.error;

  const activeTenantAdminCount = useMemo(
    () => memberships.filter((m) => m.status === "active" && m.role_code === "tenant_admin").length,
    [memberships],
  );

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return memberships;
    const roleName = (code: string | null) => roles.find((r) => r.code === code)?.name ?? code ?? "";
    return memberships.filter(
      (m) =>
        m.user_display_name.toLowerCase().includes(q) ||
        m.user_email.toLowerCase().includes(q) ||
        roleName(m.role_code).toLowerCase().includes(q),
    );
  }, [memberships, roles, search]);

  const managingMembership = memberships.find((m) => m.id === managingId) ?? null;

  function handleAddUser(payload: { userId: string; roleCode: string }) {
    setAddError(null);
    createMutation.mutate(
      { user_id: payload.userId, role_code: payload.roleCode },
      {
        onSuccess: () => setAdding(false),
        onError: (error) => setAddError(errorMessage(error)),
      },
    );
  }

  function handleManage(membership: MembershipWithUserRead) {
    setManageError(null);
    setManagingId(membership.id);
  }

  function handleSaveRole(roleCode: string) {
    if (!managingMembership) return;
    setManageError(null);
    changeRoleMutation.mutate(
      { membershipId: managingMembership.id, payload: { role_code: roleCode } },
      { onError: (error) => setManageError(errorMessage(error)) },
    );
  }

  function handleDeactivate() {
    if (!managingMembership) return;
    setManageError(null);
    deactivateMutation.mutate(managingMembership.id, {
      onError: (error) => setManageError(errorMessage(error)),
    });
  }

  function handleReactivate() {
    if (!managingMembership) return;
    setManageError(null);
    reactivateMutation.mutate(managingMembership.id, {
      onError: (error) => setManageError(errorMessage(error)),
    });
  }

  return (
    <StandaloneShell>
      <PageHeader
        title="Users & Roles"
        breadcrumbs={<Breadcrumbs items={[{ label: "Home", href: "/farms" }, { label: "Users & Roles" }]} />}
        actions={
          isTenantAdmin &&
          !adding && (
            <Button variant="primary" onClick={() => setAdding(true)}>
              <PlusCircle aria-hidden="true" className="h-4 w-4" />
              Add User
            </Button>
          )
        }
      />

      {isLoading && <LoadingSkeleton rows={4} label="Loading users" />}
      {loadError && (
        <ErrorState
          error={loadError}
          onRetry={() => {
            membershipsQuery.refetch();
            rolesQuery.refetch();
          }}
        />
      )}

      {!isLoading && !loadError && (
        <>
          {isTenantAdmin && adding && (
            <AddUserPanel
              roles={roles}
              onCancel={() => {
                setAdding(false);
                setAddError(null);
              }}
              onSubmit={handleAddUser}
              isSubmitting={createMutation.isPending}
              serverError={addError}
            />
          )}

          {isTenantAdmin && managingMembership && (
            <ManageUserPanel
              membership={managingMembership}
              roles={roles}
              isSelf={bootstrap?.user?.id === managingMembership.user_id}
              isLastActiveTenantAdmin={
                managingMembership.status === "active" &&
                managingMembership.role_code === "tenant_admin" &&
                activeTenantAdminCount <= 1
              }
              onClose={() => {
                setManagingId(null);
                setManageError(null);
              }}
              onSaveRole={handleSaveRole}
              onDeactivate={handleDeactivate}
              onReactivate={handleReactivate}
              isSavingRole={changeRoleMutation.isPending}
              isDeactivating={deactivateMutation.isPending}
              isReactivating={reactivateMutation.isPending}
              serverError={manageError}
            />
          )}

          {memberships.length === 0 && (
            <EmptyState title="No users yet" description="Add the first user to this tenant." />
          )}

          {memberships.length > 0 && (
            <>
              <div className="mb-4 max-w-xs">
                <input
                  type="search"
                  placeholder="Search by name, email, or role…"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  className="min-h-11 w-full rounded-md border border-border-subtle bg-surface px-3 text-sm text-ink focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-600"
                />
              </div>
              <UsersRolesTable
                memberships={filtered}
                roles={roles}
                currentUserId={bootstrap?.user?.id ?? null}
                canManage={isTenantAdmin}
                onManage={handleManage}
              />
            </>
          )}
        </>
      )}
    </StandaloneShell>
  );
}
