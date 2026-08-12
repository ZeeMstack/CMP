/**
 * Shared identity-header resolution for every server route that calls
 * FastAPI (AUTH-001B2). Built on top of AUTH-001B1's own boundaries
 * (`auth-mode.ts`, `session.ts`) -- this module does not re-implement
 * bearer-token acquisition or dev/test identity resolution, it only
 * assembles the right *headers* for two distinct call shapes:
 *
 *  - `resolveIdentityForAuthMe`: the tenant-UNSCOPED shape used to call
 *    GET /auth/me. Never carries a tenant header in any mode.
 *  - `resolveIdentityForTenantScopedCall`: the shape used for every other
 *    (tenant-scoped) backend call, given whatever tenant is currently
 *    selected (or null).
 *
 * Used by app/api/[...path]/route.ts, app/api/auth/bootstrap/route.ts,
 * and app/api/tenant/select/route.ts so all three agree on identical
 * semantics instead of drifting independently.
 */

import type { AuthMode, BypassIdentity } from "@/lib/server/auth-mode";
import { devIdentity, testIdentity } from "@/lib/server/auth-mode";
import { getCmpApiAccessToken, SessionExpiredError } from "@/lib/server/session";

export type UpstreamIdentityError = { status: number; body: Record<string, unknown> };

export type UpstreamIdentityResult =
  | { ok: true; headers: Record<string, string> }
  | { ok: false; error: UpstreamIdentityError };

/** `devIdentity()`/`testIdentity()` throw when their required env vars
 * are incomplete -- caught here (rather than at each of the three call
 * sites that use this module) so every caller gets the same fail-closed
 * `500 auth_configuration_error` mapping automatically. */
function resolveBypassIdentityOrError(
  mode: "dev" | "test",
): { ok: true; identity: BypassIdentity } | { ok: false; error: UpstreamIdentityError } {
  try {
    return { ok: true, identity: mode === "dev" ? devIdentity() : testIdentity() };
  } catch (err) {
    return {
      ok: false,
      error: { status: 500, body: { error: "auth_configuration_error", detail: (err as Error).message } },
    };
  }
}

/**
 * Resolves headers for the tenant-unscoped GET /auth/me call. In dev/test
 * mode, only X-Dev-User-Id is sent -- FastAPI's `require_authenticated_principal`
 * (the dependency /auth/me uses) never consults X-Dev-Tenant-Id, and
 * omitting it here keeps the "bootstrap identity tenant" configuration
 * value from ever looking like an operational tenant selection (see
 * resolveIdentityForTenantScopedCall's doc comment).
 *
 * Real mode (AUTH-001C.2): `getCmpApiAccessToken()` is the sole,
 * authoritative real-auth check -- there is no separate `getSession()`
 * precheck. The SDK's `getAccessToken()` already resolves the current
 * Auth0-managed session internally and throws when no usable session
 * exists (see session.ts), so a precheck would only duplicate that work
 * and risk drifting out of sync with it. Any failure -- no session, an
 * unrefreshable/revoked session, or any other SDK failure -- surfaces
 * uniformly as `SessionExpiredError` and maps to the same stable 401.
 */
export async function resolveIdentityForAuthMe(mode: AuthMode): Promise<UpstreamIdentityResult> {
  if (mode === "dev" || mode === "test") {
    const identity = resolveBypassIdentityOrError(mode);
    if (!identity.ok) return identity;
    return { ok: true, headers: { "X-Dev-User-Id": identity.identity.userId } };
  }

  try {
    const token = await getCmpApiAccessToken();
    return { ok: true, headers: { Authorization: `Bearer ${token}` } };
  } catch (err) {
    if (err instanceof SessionExpiredError) {
      return { ok: false, error: { status: 401, body: { error: "session_expired" } } };
    }
    throw err;
  }
}

/**
 * Resolves headers for a tenant-scoped backend call.
 *
 * Real mode: attaches `X-CMP-Tenant-Id` only when `selectedTenantId` is
 * present; if absent, the request still proceeds with no tenant header,
 * deliberately leaving FastAPI's own 400 ("X-CMP-Tenant-Id is required")
 * as the authoritative response -- never fabricated here.
 *
 * Dev/test mode: the *configured* CMP_DEV_TENANT_ID/CMP_TEST_TENANT_ID is
 * a bootstrap-identity value only -- it establishes who the dev/test
 * *user* is for /auth/me, and must never be silently reused as an
 * operational tenant selection for a business request. If no tenant has
 * actually been selected (via the same cookie real mode uses), this
 * returns a stable `tenant_selection_required` error instead of ever
 * substituting the configured tenant. When a tenant *has* been selected,
 * it becomes the effective `X-Dev-Tenant-Id`, while `X-Dev-User-Id`
 * always remains the configured dev/test user -- this is what lets a
 * dev/test identity with multiple memberships actually exercise real
 * tenant switching against the backend's dev-auth mechanism.
 */
export async function resolveIdentityForTenantScopedCall(
  mode: AuthMode,
  selectedTenantId: string | null,
): Promise<UpstreamIdentityResult> {
  if (mode === "dev" || mode === "test") {
    if (!selectedTenantId) {
      return { ok: false, error: { status: 400, body: { error: "tenant_selection_required" } } };
    }
    const identity = resolveBypassIdentityOrError(mode);
    if (!identity.ok) return identity;
    return {
      ok: true,
      headers: { "X-Dev-Tenant-Id": selectedTenantId, "X-Dev-User-Id": identity.identity.userId },
    };
  }

  try {
    const token = await getCmpApiAccessToken();
    const headers: Record<string, string> = { Authorization: `Bearer ${token}` };
    if (selectedTenantId) {
      headers["X-CMP-Tenant-Id"] = selectedTenantId;
    }
    return { ok: true, headers };
  } catch (err) {
    if (err instanceof SessionExpiredError) {
      return { ok: false, error: { status: 401, body: { error: "session_expired" } } };
    }
    throw err;
  }
}
