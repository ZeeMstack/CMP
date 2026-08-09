import { NextRequest, NextResponse } from "next/server";

import { getPilotIdentity } from "@/lib/server/pilot-identity";

/**
 * Server-side, read-only proxy to the CMP backend.
 *
 * GET ONLY -- deliberately. FE-001 is a read-only pilot; exporting only GET
 * from this route guarantees the fixed pilot identity (see
 * lib/server/pilot-identity.ts) can never be used to perform a write against
 * the backend, even by accident. Do not add POST/PUT/PATCH/DELETE here
 * without first re-deciding the identity/auth strategy (see that file's
 * doc comment).
 *
 * Attaches the dev-auth headers server-side only -- the browser never sees
 * or can set X-Dev-Tenant-Id / X-Dev-User-Id.
 */
export async function GET(request: NextRequest, { params }: { params: Promise<{ path: string[] }> }) {
  const { path } = await params;
  let identity;
  try {
    identity = getPilotIdentity();
  } catch (error) {
    return NextResponse.json(
      { error: "pilot_identity_misconfigured", detail: (error as Error).message },
      { status: 500 },
    );
  }

  const upstreamUrl = new URL(`/${path.join("/")}`, identity.apiBaseUrl);
  upstreamUrl.search = request.nextUrl.search;

  let upstreamResponse: Response;
  try {
    upstreamResponse = await fetch(upstreamUrl, {
      method: "GET",
      headers: {
        Accept: "application/json",
        "X-Dev-Tenant-Id": identity.tenantId,
        "X-Dev-User-Id": identity.userId,
      },
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
