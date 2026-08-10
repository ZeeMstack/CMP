/**
 * Resolves which identity mechanism the BFF proxy should use for the
 * current process: real Auth0-issued bearer tokens, the development-only
 * dev-header bypass, or the test-only bypass used exclusively by the
 * Playwright suite. This module owns the fail-closed rules -- callers
 * (the proxy route) only ever branch on the returned `AuthMode`, never
 * re-implement the guard logic themselves.
 *
 * Mirrors the backend's own fail-closed pattern
 * (`app/core/dev_auth.py::check_dev_auth_startup_invariant`,
 * `app/core/settings.py::check_oidc_startup_invariant`): a misconfigured
 * bypass must refuse to serve, never silently fall back to something
 * weaker or silently ignore the flag.
 */

import { requireEnv } from "@/lib/server/env";

export type AuthMode = "dev" | "test" | "real";

export interface BypassIdentity {
  tenantId: string;
  userId: string;
}

function isProductionRuntime(): boolean {
  return process.env.NODE_ENV === "production";
}

/** Distinctive, non-boolean sentinel -- deliberately harder to set by
 * accident than a plain "true", so this can never become "ordinary
 * deployed authentication" through a careless env var. */
const TEST_BYPASS_SENTINEL = "playwright-e2e-only";

/**
 * Determines the active auth mode for this process. Throws (fail-closed)
 * rather than returning a mode if the configuration is ambiguous or
 * unsafe -- callers must let this exception propagate into a hard
 * failure (see `instrumentation.ts` for the startup-time check, and the
 * proxy route for the per-request check), never catch-and-fall-back.
 */
export function resolveAuthMode(): AuthMode {
  const devBypassRequested = process.env.CMP_DEV_AUTH_BYPASS === "true";
  const testBypassRequested = process.env.CMP_TEST_AUTH_BYPASS === TEST_BYPASS_SENTINEL;

  if (devBypassRequested && testBypassRequested) {
    throw new Error(
      "CMP_DEV_AUTH_BYPASS and CMP_TEST_AUTH_BYPASS are both active -- ambiguous auth mode, refusing to serve.",
    );
  }

  if (devBypassRequested) {
    if (isProductionRuntime()) {
      throw new Error(
        "CMP_DEV_AUTH_BYPASS=true is set but NODE_ENV=production. The development identity bypass must " +
          "never run in a production-shaped runtime -- refusing to serve rather than weakening this invariant.",
      );
    }
    return "dev";
  }

  if (testBypassRequested) {
    return "test";
  }

  return "real";
}

export function devIdentity(): BypassIdentity {
  return { tenantId: requireEnv("CMP_DEV_TENANT_ID"), userId: requireEnv("CMP_DEV_USER_ID") };
}

export function testIdentity(): BypassIdentity {
  return { tenantId: requireEnv("CMP_TEST_TENANT_ID"), userId: requireEnv("CMP_TEST_USER_ID") };
}
