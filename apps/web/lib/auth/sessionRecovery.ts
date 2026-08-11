/**
 * CMP-owned centralized session-recovery coordinator (AUTH-001B3).
 *
 * `lib/api/client.ts` (every business API call) only ever calls
 * `triggerSessionRecovery()` -- it has no router/QueryClient dependency
 * of its own. `SessionRecoveryCoordinator` (a single component mounted
 * once near the app root) registers the actual handler: clear the
 * QueryClient, then navigate to `/login` with a safe returnTo. This
 * keeps `client.ts` a plain fetch wrapper and keeps routing logic out of
 * the data-fetching layer.
 *
 * Any 401 from a tenant-scoped business request means the same thing
 * regardless of its body shape -- a bare upstream FastAPI 401 and the
 * BFF's own `{"error":"session_expired"}` are handled identically here;
 * neither is parsed for provider-specific detail.
 */

export type SessionRecoveryHandler = (returnToPath: string) => void;

let handler: SessionRecoveryHandler | null = null;
let recoveryTriggered = false;

export function registerSessionRecoveryHandler(next: SessionRecoveryHandler | null): void {
  handler = next;
}

/**
 * Called by lib/api/client.ts whenever a tenant-scoped business request
 * comes back 401. Deduplicated: a burst of concurrent failing requests
 * (e.g. Batch Detail's several concurrent queries) triggers the recovery
 * handler at most once -- never a redirect storm.
 */
export function triggerSessionRecovery(returnToPath: string): void {
  if (recoveryTriggered) return;
  recoveryTriggered = true;
  handler?.(returnToPath);
}

/** Called once a fresh, successfully-authenticated bootstrap is
 * observed, so a later, genuinely new session-expiry event can trigger
 * recovery again. */
export function resetSessionRecoveryDedupe(): void {
  recoveryTriggered = false;
}

/** Test-only: fully resets module state between test cases. */
export function resetSessionRecoveryForTesting(): void {
  handler = null;
  recoveryTriggered = false;
}
