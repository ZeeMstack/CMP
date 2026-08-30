import type { ReactNode } from "react";

import { LinkButton } from "@/components/admin/LinkButton";
import { StatusBadge } from "@/components/StatusBadge";
import { Button } from "@/components/ui/Button";
import type { PlatformTenantOnboardingResponse } from "@/lib/api/client";

function DetailRow({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <dt className="text-xs uppercase tracking-wide text-ink-muted">{label}</dt>
      <dd className="mt-1 text-sm font-medium text-ink">{children}</dd>
    </div>
  );
}

/**
 * PILOT-SETUP-001B3: factual confirmation only -- no tokens/credentials/
 * secrets, and deliberately no "Open Tenant" action. B2 guarantees the
 * requesting Platform Admin receives no Membership from this command (only
 * the `initial_admin` identity does), so the only honest next steps are
 * viewing the Tenant's platform metadata, returning to the list, or
 * starting another onboarding -- never entering the new Tenant's
 * operational workspace, which this Platform Admin was not granted access
 * to.
 */
export function TenantOnboardingConfirmation({
  result,
  onCreateAnother,
}: {
  result: PlatformTenantOnboardingResponse;
  onCreateAnother: () => void;
}) {
  return (
    <div className="flex flex-col gap-6">
      <div role="status" className="rounded-lg border border-brand-200 bg-brand-50 px-4 py-3">
        <p className="font-medium text-brand-900">Tenant created. Initial Tenant Administrator established.</p>
      </div>

      <section className="rounded-xl border border-border-subtle bg-surface p-4">
        <h2 className="mb-3 font-serif text-base font-semibold text-ink">Tenant</h2>
        <dl className="grid grid-cols-1 gap-x-4 gap-y-3 sm:grid-cols-3">
          <DetailRow label="Code">{result.tenant.code}</DetailRow>
          <DetailRow label="Name">{result.tenant.name}</DetailRow>
          <DetailRow label="Status">
            <StatusBadge label={result.tenant.status} tone={result.tenant.status === "active" ? "active" : "neutral"} />
          </DetailRow>
        </dl>
      </section>

      <section className="rounded-xl border border-border-subtle bg-surface p-4">
        <h2 className="mb-3 font-serif text-base font-semibold text-ink">Initial Administrator</h2>
        <dl className="grid grid-cols-1 gap-x-4 gap-y-3 sm:grid-cols-3">
          <DetailRow label="Display name">{result.admin_user.display_name}</DetailRow>
          <DetailRow label="Email">{result.admin_user.email}</DetailRow>
          <DetailRow label="OIDC issuer">{result.admin_user.oidc_issuer}</DetailRow>
          <DetailRow label="OIDC subject">{result.admin_user.oidc_subject}</DetailRow>
          <DetailRow label="User account">
            {result.admin_user_created ? "Newly created" : "Existing user resolved"}
          </DetailRow>
        </dl>
      </section>

      <section className="rounded-xl border border-border-subtle bg-surface p-4">
        <h2 className="mb-3 font-serif text-base font-semibold text-ink">Membership</h2>
        <dl className="grid grid-cols-1 gap-x-4 gap-y-3 sm:grid-cols-3">
          <DetailRow label="Role">{result.membership.role_code ?? "tenant_admin"}</DetailRow>
          <DetailRow label="Status">{result.membership.status}</DetailRow>
        </dl>
      </section>

      <p className="text-sm text-ink-muted">
        You have not been added as a member of this Tenant. The administrator above will sign in separately, under
        their own OIDC identity, to continue setup.
      </p>

      <div className="flex flex-wrap gap-3">
        <LinkButton variant="primary" href={`/admin/tenants/${result.tenant.id}`}>
          View Tenant
        </LinkButton>
        <LinkButton variant="secondary" href="/admin/tenants">
          Back to Tenants
        </LinkButton>
        <Button variant="secondary" onClick={onCreateAnother}>
          Create Another Tenant
        </Button>
      </div>
    </div>
  );
}
