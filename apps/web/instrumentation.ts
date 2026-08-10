/**
 * Startup-time fail-closed check (AUTH-001B1), mirroring the backend's own
 * pattern (`app/core/dev_auth.py::check_dev_auth_startup_invariant`,
 * `app/core/settings.py::check_oidc_startup_invariant`): a misconfigured
 * auth mode should fail loudly at server startup, in deploy logs, rather
 * than silently serving broken/ambiguous authentication until the first
 * request happens to hit it.
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
  const { resolveAuthMode } = await import("@/lib/server/auth-mode");
  resolveAuthMode();
}
