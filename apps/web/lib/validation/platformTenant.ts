import { z } from "zod";

import type { PlatformTenantOnboardingCreate } from "@/lib/api/client";

/**
 * PILOT-SETUP-001B3: mirrors the backend's own validation exactly (see
 * `app.schemas.tenant.TenantCreate` / `app.schemas.platform_tenant
 * .PlatformTenantOnboardingAdminCreate`) -- every field is trimmed and
 * required, nothing more. No length ceiling, format, or normalization is
 * invented here: the backend enforces uniqueness (Tenant code, OIDC
 * identity, email) itself and is the sole source of truth for those
 * conflicts (surfaced as 409s, not client-side validation).
 */
const requiredTrimmed = (label: string) => z.string().trim().min(1, `${label} is required`);

export const createTenantFormSchema = z.object({
  tenantCode: requiredTrimmed("Tenant code"),
  tenantName: requiredTrimmed("Tenant name"),
  oidcIssuer: requiredTrimmed("OIDC issuer"),
  oidcSubject: requiredTrimmed("OIDC subject"),
  email: requiredTrimmed("Email"),
  displayName: requiredTrimmed("Display name"),
});
export type CreateTenantFormValues = z.infer<typeof createTenantFormSchema>;

export const DEFAULT_CREATE_TENANT_FORM_VALUES: CreateTenantFormValues = {
  tenantCode: "",
  tenantName: "",
  oidcIssuer: "",
  oidcSubject: "",
  email: "",
  displayName: "",
};

/** The one `POST /platform/tenants` request shape -- no idempotency key,
 * since `PlatformTenantOnboardingCreate` has none (unlike e.g.
 * `GreenhouseSetupCreate`'s `client_command_id`); inventing one here would
 * send a field the backend does not define. */
export function buildPlatformTenantOnboardingPayload(
  values: CreateTenantFormValues,
): PlatformTenantOnboardingCreate {
  return {
    tenant: { code: values.tenantCode, name: values.tenantName },
    initial_admin: {
      oidc_issuer: values.oidcIssuer,
      oidc_subject: values.oidcSubject,
      email: values.email,
      display_name: values.displayName,
    },
  };
}
