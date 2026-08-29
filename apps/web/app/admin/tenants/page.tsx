"use client";

import Link from "next/link";

import { PlatformAccessDeniedState } from "@/components/admin/PlatformAccessDeniedState";
import { Breadcrumbs } from "@/components/Breadcrumbs";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { LoadingSkeleton } from "@/components/LoadingSkeleton";
import { PageHeader } from "@/components/PageHeader";
import { StatusBadge, type StatusTone } from "@/components/StatusBadge";
import { Button } from "@/components/ui/Button";
import { AppError } from "@/lib/errors/adapter";
import { usePlatformTenants } from "@/lib/query/hooks";

function tenantStatusTone(status: string): StatusTone {
  return status === "active" ? "active" : "neutral";
}

export default function PlatformTenantsPage() {
  const { data: tenants, isLoading, error, refetch } = usePlatformTenants();
  const isPlatformAccessDenied = error instanceof AppError && error.kind === "permission_error";

  return (
    <div>
      <PageHeader
        title="Tenants"
        breadcrumbs={<Breadcrumbs items={[{ label: "Platform Administration" }, { label: "Tenants" }]} />}
        actions={
          <Link href="/admin/tenants/new">
            <Button variant="primary">Create Tenant</Button>
          </Link>
        }
      />

      {isLoading && <LoadingSkeleton rows={4} label="Loading tenants" />}

      {!isLoading && error && isPlatformAccessDenied && <PlatformAccessDeniedState />}
      {!isLoading && error && !isPlatformAccessDenied && <ErrorState error={error} onRetry={() => refetch()} />}

      {!isLoading && !error && tenants && tenants.length === 0 && (
        <EmptyState
          title="No tenants yet"
          description="Create the first Tenant to get started."
          action={
            <Link href="/admin/tenants/new">
              <Button variant="primary">Create Tenant</Button>
            </Link>
          }
        />
      )}

      {!isLoading && !error && tenants && tenants.length > 0 && (
        <div className="overflow-x-auto rounded-xl border border-border-subtle bg-surface">
          <table className="w-full min-w-[480px] text-left text-sm">
            <thead className="border-b border-border-subtle bg-surface-subtle text-xs uppercase tracking-wide text-ink-muted">
              <tr>
                <th scope="col" className="px-4 py-3 font-medium">Code</th>
                <th scope="col" className="px-4 py-3 font-medium">Name</th>
                <th scope="col" className="px-4 py-3 font-medium">Status</th>
                <th scope="col" className="px-4 py-3 font-medium">
                  <span className="sr-only">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border-subtle">
              {tenants.map((tenant) => (
                <tr key={tenant.id}>
                  <td className="px-4 py-3 font-medium text-ink">{tenant.code}</td>
                  <td className="px-4 py-3 text-ink">{tenant.name}</td>
                  <td className="px-4 py-3">
                    <StatusBadge label={tenant.status} tone={tenantStatusTone(tenant.status)} />
                  </td>
                  <td className="px-4 py-3 text-right">
                    <Link
                      href={`/admin/tenants/${tenant.id}`}
                      className="inline-flex min-h-11 items-center text-sm font-medium text-brand-700 hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-600"
                    >
                      View Tenant
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
