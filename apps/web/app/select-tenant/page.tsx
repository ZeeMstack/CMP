"use client";

import { useRouter } from "next/navigation";

import { EmptyState } from "@/components/EmptyState";
import { LoadingSkeleton } from "@/components/LoadingSkeleton";
import { humanizeEnumCode } from "@/lib/format/humanize";
import { useAuthBootstrap } from "@/lib/auth/AuthBootstrapProvider";

/**
 * A real place for a user with >1 membership to explicitly choose a
 * tenant (AUTH-001B2). B3 will later own automatic route guards that
 * redirect *to* this page when appropriate -- this page only renders the
 * choice and invokes the same `selectTenant()` action AppShell's
 * TenantSelector uses; it never duplicates selection/reconciliation
 * logic itself.
 */
export default function SelectTenantPage() {
  const { bootstrap, isLoading, selectTenant, isSwitchingTenant } = useAuthBootstrap();
  const router = useRouter();

  if (isLoading || !bootstrap) {
    return (
      <div className="mx-auto max-w-lg px-4 py-16">
        <LoadingSkeleton rows={3} label="Loading" />
      </div>
    );
  }

  if (bootstrap.status !== "authenticated") {
    // Truthful transitional state only -- B3 owns polished access-denied/
    // login-recovery routing for unauthenticated/not_provisioned/error.
    return (
      <div className="mx-auto max-w-lg px-4 py-16">
        <EmptyState title="Not signed in" description="Sign in to select a tenant." />
      </div>
    );
  }

  if (bootstrap.memberships.length === 0) {
    return (
      <div className="mx-auto max-w-lg px-4 py-16">
        <EmptyState
          title="No tenant access"
          description="Your account is not yet associated with any tenant. Contact an administrator."
        />
      </div>
    );
  }

  async function handleSelect(tenantId: string) {
    const result = await selectTenant(tenantId);
    if (result.ok) {
      router.push("/farms");
    }
  }

  return (
    <div className="mx-auto max-w-lg px-4 py-16">
      <h1 className="mb-1 text-xl font-semibold text-ink">GrowCMP</h1>
      <p className="mb-6 text-sm text-ink-muted">Choose a tenant.</p>
      <ul className="space-y-2">
        {bootstrap.memberships.map((membership) => (
          <li key={membership.tenantId}>
            <button
              type="button"
              onClick={() => handleSelect(membership.tenantId)}
              disabled={isSwitchingTenant}
              className="block w-full min-h-11 rounded-lg border border-border-subtle bg-surface px-4 py-3 text-left hover:border-brand-300 hover:bg-brand-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-600 disabled:opacity-60"
            >
              <span className="font-medium text-ink">{membership.tenantName}</span>
              <span className="ml-2 text-sm text-ink-muted">
                {membership.tenantCode} · {humanizeEnumCode(membership.roleCode)}
              </span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
