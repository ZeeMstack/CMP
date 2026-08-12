import { NextRequest, NextResponse } from "next/server";

import { requireEnv } from "@/lib/server/env";
import { readSelectedTenantId } from "@/lib/server/tenant-selection";
import { resolveAuthMode } from "@/lib/server/auth-mode";
import { resolveIdentityForAuthMe, resolveIdentityForTenantScopedCall } from "@/lib/server/upstream-identity";

/**
 * Server-side, read-only proxy to the CMP backend (AUTH-001B1, tenant
 * headers added in AUTH-001B2).
 *
 * GET ONLY -- deliberately, unchanged since FE-001/FE-002B. No business
 * mutation UX exists yet; widening this to other HTTP verbs is a future
 * ticket's decision, not a side effect of adding authentication or tenant
 * selection. Tenant selection itself has its own dedicated, narrow
 * endpoint (`POST /api/tenant/select`) -- this generic catch-all never
 * gains a POST handler for it.
 *
 * Identity/tenant headers are resolved via lib/server/upstream-identity.ts
 * (shared with the bootstrap and tenant-selection routes):
 *  - GET /auth/me is tenant-unscoped in every mode -- no X-CMP-Tenant-Id,
 *    no X-Dev-Tenant-Id are ever attached to it.
 *  - Every other path is treated as tenant-scoped. In real mode, the
 *    currently-selected tenant (from the `cmp_tenant_id` cookie, if any)
 *    is attached as X-CMP-Tenant-Id; if none is selected, no tenant
 *    header is sent at all and FastAPI's own 400 remains authoritative.
 *    In dev/test mode, an unselected tenant is refused here directly
 *    (stable `tenant_selection_required` 400) rather than silently
 *    reusing the configured bootstrap identity's tenant as an
 *    operational selection.
 */
export async function GET(request: NextRequest, { params }: { params: Promise<{ path: string[] }> }) {
  const { path } = await params;

  let apiBaseUrl: string;
  try {
    apiBaseUrl = requireEnv("CMP_API_BASE_URL");
  } catch (error) {
    return NextResponse.json(
      { error: "proxy_misconfigured", detail: (error as Error).message },
      { status: 500 },
    );
  }

  let mode: ReturnType<typeof resolveAuthMode>;
  try {
    mode = resolveAuthMode();
  } catch (error) {
    // Fail-closed: an ambiguous or unsafe bypass configuration must never
    // silently fall through to any identity mechanism.
    return NextResponse.json(
      { error: "auth_configuration_error", detail: (error as Error).message },
      { status: 500 },
    );
  }

  const isAuthMe = path.length === 2 && path[0] === "auth" && path[1] === "me";

  const identity = isAuthMe
    ? await resolveIdentityForAuthMe(mode)
    : await resolveIdentityForTenantScopedCall(mode, readSelectedTenantId(request));

  if (!identity.ok) {
    return NextResponse.json(identity.error.body, { status: identity.error.status });
  }

  const upstreamUrl = new URL(`/${path.join("/")}`, apiBaseUrl);
  upstreamUrl.search = request.nextUrl.search;

  let upstreamResponse: Response;
  try {
    upstreamResponse = await fetch(upstreamUrl, {
      method: "GET",
      headers: { Accept: "application/json", ...identity.headers },
      cache: "no-store",
    });
  } catch {
    return NextResponse.json({ error: "network_error", detail: "Could not reach the backend" }, { status: 502 });
  }

  const body = await upstreamResponse.text();
  return new NextResponse(body, {
    status: upstreamResponse.status,
    headers: { "Content-Type": upstreamResponse.headers.get("Content-Type") ?? "application/json" },
  });
}
