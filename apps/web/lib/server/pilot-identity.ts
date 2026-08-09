/**
 * INTERNAL PILOT ONLY -- NOT AUTHENTICATION.
 *
 * There is no login, session, or per-user identity in FE-001. Every request
 * this application makes to the backend is attributed to one fixed
 * tenant/user pair, configured here from server-only environment variables.
 * The backend's own dev-auth dependency (`app/core/dev_auth.py`) remains the
 * authority that validates these values are a real, active tenant/user/
 * membership -- this module only decides which identity to *send*.
 *
 * This file must only ever be imported from server-side code (Route
 * Handlers, Server Components) -- never from a "use client" module, and the
 * values it reads must never be exposed via NEXT_PUBLIC_* variables.
 *
 * This mechanism must be replaced before:
 *   - any write/mutation workflow ships (a shared identity cannot support
 *     per-command audit attribution), or
 *   - any user outside a controlled internal pilot gets access.
 */

export interface PilotIdentity {
  apiBaseUrl: string;
  tenantId: string;
  userId: string;
}

function requireEnv(name: string): string {
  const value = process.env[name];
  if (!value) {
    throw new Error(
      `Missing required server environment variable ${name}. See apps/web/.env.example. ` +
        "This is the internal-pilot identity configuration, not end-user authentication.",
    );
  }
  return value;
}

export function getPilotIdentity(): PilotIdentity {
  return {
    apiBaseUrl: requireEnv("CMP_API_BASE_URL"),
    tenantId: requireEnv("CMP_PILOT_TENANT_ID"),
    userId: requireEnv("CMP_PILOT_USER_ID"),
  };
}
