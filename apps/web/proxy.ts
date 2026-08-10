/**
 * Next.js 16 integration point for @auth0/nextjs-auth0 (AUTH-001B1).
 *
 * Next.js 16 renamed the middleware entry point from `middleware.ts` to
 * `proxy.ts`; the installed SDK (@auth0/nextjs-auth0@4.26.0) documents
 * `proxy.ts` as the recommended integration for Next.js 16 specifically
 * (its own docs still show `middleware.ts` for Next.js 15). This repo is
 * on Next.js 16.2.12, so `proxy.ts` is the correct file -- see the
 * AUTH-001B audit for the verification.
 *
 * This file's only responsibility is Auth0's own session/route
 * integration (login, callback, logout, session rolling) via
 * `auth0.middleware()`. No CMP-specific business logic belongs here.
 *
 * In dev/test bypass mode (see lib/server/auth-mode.ts), `auth0.middleware()`
 * must NOT run at all: it runs on every matched request (not only
 * `/auth/*` ones), so calling it unconditionally would construct the
 * `Auth0Client` -- and therefore require real `AUTH0_*` configuration --
 * on every navigation, defeating the entire point of the bypass modes.
 * Resolving the auth mode first and passing bypass requests straight
 * through is what actually lets `next dev`/`next build`/`next start` run
 * without a configured Auth0 tenant.
 */

import { NextResponse } from "next/server";

import { resolveAuthMode } from "@/lib/server/auth-mode";
import { getAuth0Client } from "@/lib/server/auth0";

export async function proxy(request: Request) {
  const mode = resolveAuthMode();
  if (mode !== "real") {
    return NextResponse.next();
  }
  return getAuth0Client().middleware(request);
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico|sitemap.xml|robots.txt).*)"],
};
