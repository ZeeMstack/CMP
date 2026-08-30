import { NextRequest, NextResponse } from "next/server";

import { requireEnv } from "@/lib/server/env";
import { isSameOriginRequest } from "@/lib/server/same-origin";
import { readSelectedTenantId } from "@/lib/server/tenant-selection";
import { resolveAuthMode } from "@/lib/server/auth-mode";
import { resolveIdentityForAuthMe, resolveIdentityForTenantScopedCall } from "@/lib/server/upstream-identity";

/**
 * Server-side proxy to the CMP backend (AUTH-001B1, tenant headers added
 * in AUTH-001B2; POST added by FARM-SETUP-001 for the first business
 * mutation UX -- Farm Setup's Greenhouse creation command).
 *
 * Identity/tenant headers are resolved via lib/server/upstream-identity.ts
 * (shared with the bootstrap and tenant-selection routes):
 *  - GET /auth/me is tenant-unscoped in every mode -- no X-CMP-Tenant-Id,
 *    no X-Dev-Tenant-Id are ever attached to it.
 *  - Every `/platform/*` path (PILOT-SETUP-001B3) is likewise
 *    tenant-unscoped: `require_platform_admin` is WHO-only authorization
 *    (see app/core/platform_auth.py), structurally independent of any
 *    TenantContext, and a genuine Platform Admin may legitimately hold
 *    zero tenant memberships / have no tenant selected. Routing these
 *    through the tenant-scoped resolver would wrongly attach whatever
 *    tenant happens to be selected in real mode, and would hard-fail with
 *    `tenant_selection_required` in dev/test mode even though no tenant
 *    is relevant to the call at all.
 *  - Every other path is treated as tenant-scoped. In real mode, the
 *    currently-selected tenant (from the `cmp_tenant_id` cookie, if any)
 *    is attached as X-CMP-Tenant-Id; if none is selected, no tenant
 *    header is sent at all and FastAPI's own 400 remains authoritative.
 *    In dev/test mode, an unselected tenant is refused here directly
 *    (stable `tenant_selection_required` 400) rather than silently
 *    reusing the configured bootstrap identity's tenant as an
 *    operational selection.
 *
 * POST never gets its own tenant-selection special case (unlike the
 * dedicated, narrow `POST /api/tenant/select` route, which this
 * catch-all still never handles) -- it reuses the exact same tenant-scoped
 * identity resolution as GET, since every current and foreseeable POST
 * target here is a tenant-scoped business command, never an auth/session
 * action.
 *
 * CSRF (FARM-SETUP-001.2): the Auth0 session cookie and `cmp_tenant_id`
 * are both `SameSite=Lax`, `HttpOnly` -- a genuine cross-site POST never
 * carries either, so it already arrives with no usable identity before
 * this route does anything. `POST` additionally checks `isSameOriginRequest`
 * (same helper already used by `/api/tenant/select` and `/api/auth/logout`)
 * as defense in depth, matching the one established convention for every
 * other state-changing Route Handler in this app.
 */
async function resolveProxyContext(request: NextRequest, path: string[]) {
  let apiBaseUrl: string;
  try {
    apiBaseUrl = requireEnv("CMP_API_BASE_URL");
  } catch (error) {
    return {
      ok: false as const,
      response: NextResponse.json(
        { error: "proxy_misconfigured", detail: (error as Error).message },
        { status: 500 },
      ),
    };
  }

  let mode: ReturnType<typeof resolveAuthMode>;
  try {
    mode = resolveAuthMode();
  } catch (error) {
    // Fail-closed: an ambiguous or unsafe bypass configuration must never
    // silently fall through to any identity mechanism.
    return {
      ok: false as const,
      response: NextResponse.json(
        { error: "auth_configuration_error", detail: (error as Error).message },
        { status: 500 },
      ),
    };
  }

  const isAuthMe = path.length === 2 && path[0] === "auth" && path[1] === "me";
  const isPlatformScoped = path.length > 0 && path[0] === "platform";

  const identity = isAuthMe || isPlatformScoped
    ? await resolveIdentityForAuthMe(mode)
    : await resolveIdentityForTenantScopedCall(mode, readSelectedTenantId(request));

  if (!identity.ok) {
    return { ok: false as const, response: NextResponse.json(identity.error.body, { status: identity.error.status }) };
  }

  // FARM-SETUP-001.1 section 11: built from individually-encoded, non-empty
  // segments only -- never `path.join("/")` directly. A raw join would let
  // a segment that decodes to an empty string (e.g. path = ["", "evil.example",
  // "steal"]) produce a leading "//host/..." string, which the WHATWG URL
  // spec resolves as a protocol-relative reference that REPLACES the base's
  // host entirely (`new URL("//evil.example/x", "http://api:8000")` ->
  // `http://evil.example/x`) -- silently turning this proxy into an open
  // relay to an arbitrary external host. Filtering empty segments and
  // encoding each one guarantees the joined string can never start with more
  // than a single "/", so the base's own host can never be overridden.
  const safePath = path.filter((segment) => segment.length > 0).map(encodeURIComponent).join("/");
  const upstreamUrl = new URL(`/${safePath}`, apiBaseUrl);
  upstreamUrl.search = request.nextUrl.search;
  return { ok: true as const, upstreamUrl, headers: identity.headers };
}

function relayResponse(upstreamResponse: Response, body: string) {
  return new NextResponse(body, {
    status: upstreamResponse.status,
    headers: { "Content-Type": upstreamResponse.headers.get("Content-Type") ?? "application/json" },
  });
}

export async function GET(request: NextRequest, { params }: { params: Promise<{ path: string[] }> }) {
  const { path } = await params;
  const ctx = await resolveProxyContext(request, path);
  if (!ctx.ok) return ctx.response;

  let upstreamResponse: Response;
  try {
    upstreamResponse = await fetch(ctx.upstreamUrl, {
      method: "GET",
      headers: { Accept: "application/json", ...ctx.headers },
      cache: "no-store",
    });
  } catch {
    return NextResponse.json({ error: "network_error", detail: "Could not reach the backend" }, { status: 502 });
  }

  return relayResponse(upstreamResponse, await upstreamResponse.text());
}

export async function POST(request: NextRequest, { params }: { params: Promise<{ path: string[] }> }) {
  // FARM-SETUP-001.2 section 6/7: matches the existing convention already
  // applied to every other state-changing Route Handler in this app
  // (`/api/tenant/select`, `/api/auth/logout`) -- SameSite=Lax on both the
  // Auth0 session cookie and `cmp_tenant_id` is the PRIMARY CSRF boundary
  // (a genuine cross-site POST/fetch/form-submit never carries a Lax
  // cookie at all, so it would already arrive here with no usable
  // identity), this Origin check is defense in depth on top of that, not
  // a replacement for it. This was the one POST-capable route in the app
  // that had NOT yet had the existing `isSameOriginRequest` guard applied.
  if (!isSameOriginRequest(request)) {
    return NextResponse.json({ error: "cross_origin_rejected" }, { status: 403 });
  }

  const { path } = await params;
  const ctx = await resolveProxyContext(request, path);
  if (!ctx.ok) return ctx.response;

  const requestBody = await request.text();

  let upstreamResponse: Response;
  try {
    upstreamResponse = await fetch(ctx.upstreamUrl, {
      method: "POST",
      headers: { Accept: "application/json", "Content-Type": "application/json", ...ctx.headers },
      body: requestBody,
      cache: "no-store",
    });
  } catch {
    return NextResponse.json({ error: "network_error", detail: "Could not reach the backend" }, { status: 502 });
  }

  return relayResponse(upstreamResponse, await upstreamResponse.text());
}
