/**
 * Startup-time fail-closed check (AUTH-001B1, extended DEPLOY-001A),
 * mirroring the backend's own pattern (`app/core/dev_auth.py::check_dev_
 * auth_startup_invariant`, `app/core/settings.py::check_oidc_startup_
 * invariant`): a misconfigured auth mode, or (in a production-shaped real-
 * auth deployment) missing Auth0/CMP configuration, should fail loudly at
 * server startup, in deploy logs, rather than silently serving broken
 * authentication until the first request happens to hit it.
 *
 * This is defense in depth, not the sole enforcement -- `resolveAuthMode()`
 * is also called on every single request (proxy.ts, the BFF proxy route),
 * so the same fail-closed behavior holds even if this hook's failure
 * somehow did not halt startup in some runtime.
 *
 * Next.js only invokes `register()` for the Node.js runtime by default;
 * this module has no Edge-runtime-specific code, so no `NEXT_RUNTIME`
 * branching is needed here.
 */
export async function register() {
  const { resolveAuthMode, checkAuthStartupInvariant } = await import("@/lib/server/auth-mode");
  const mode = resolveAuthMode();
  checkAuthStartupInvariant(mode);
}
