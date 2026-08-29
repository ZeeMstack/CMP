"use client";

import { useParams } from "next/navigation";

import { PlatformAccessDeniedState } from "@/components/admin/PlatformAccessDeniedState";
import { Breadcrumbs } from "@/components/Breadcrumbs";
import { ErrorState } from "@/components/ErrorState";
import { LoadingSkeleton } from "@/components/LoadingSkeleton";
import { PageHeader } from "@/components/PageHeader";
import { StatusBadge } from "@/components/StatusBadge";
import { AppError } from "@/lib/errors/adapter";
import { usePlatformTenant } from "@/lib/query/hooks";

export default function PlatformTenantDetailPage() {
  const { tenantId } = useParams<{ tenantId: string }>();
  const { data: tenant, isLoading, error, refetch } = usePlatformTenant(tenantId);
  const isPlatformAccessDenied = error instanceof AppError && error.kind === "permission_error";

  return (
    <div>
      <PageHeader
        title={tenant ? tenant.name : "Tenant"}
        breadcrumbs={
          <Breadcrumbs
            items={[
              { label: "Platform Administration" },
              { label: "Tenants", href: "/admin/tenants" },
              { label: tenant ? tenant.code : "Tenant" },
            ]}
          />
        }
      />

      {isLoading && <LoadingSkeleton rows={3} label="Loading tenant" />}

      {!isLoading && error && isPlatformAccessDenied && <PlatformAccessDeniedState />}
      {!isLoading && error && !isPlatformAccessDenied && <ErrorState error={error} onRetry={() => refetch()} />}

      {/* Only currently-supported Tenant metadata (code/name/status) --
          B2's GET /platform/tenants/{tenant_id} returns nothing else, so
          no initial-admin summary, farm count, users, or other operational
          statistics are fabricated here. */}
      {!isLoading && !error && tenant && (
        <dl className="grid max-w-lg grid-cols-1 gap-x-6 gap-y-4 rounded-xl border border-border-subtle bg-surface p-6 sm:grid-cols-2">
          <div>
            <dt className="text-xs uppercase tracking-wide text-ink-muted">Code</dt>
            <dd className="mt-1 text-sm font-medium text-ink">{tenant.code}</dd>
          </div>
          <div>
            <dt className="text-xs uppercase tracking-wide text-ink-muted">Name</dt>
            <dd className="mt-1 text-sm font-medium text-ink">{tenant.name}</dd>
          </div>
          <div>
            <dt className="text-xs uppercase tracking-wide text-ink-muted">Status</dt>
            <dd className="mt-1">
              <StatusBadge label={tenant.status} tone={tenant.status === "active" ? "active" : "neutral"} />
            </dd>
          </div>
        </dl>
      )}
    </div>
  );
}
