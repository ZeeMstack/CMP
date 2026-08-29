/**
 * The one CMP-owned route-access decision model (AUTH-001B3). Pure
 * functions only -- no React, no router, no fetch -- so every branch is
 * directly unit-testable without mocking Next.js navigation. `AuthGate`
 * (the only consumer) is a thin wrapper that feeds this model live state
 * and executes its decisions; no page/component re-derives this logic.
 */

import { sanitizeReturnTo } from "@/lib/auth/return-to";
import type { AuthBootstrap } from "@/lib/auth/types";

export type AuthPhase =
  | "loading"
  | "unauthenticated"
  | "not_provisioned"
  | "zero_memberships"
  | "needs_tenant_selection"
  | "ready"
  | "error";

/**
 * Derives the current auth phase from AuthBootstrapProvider's own state
 * -- never issues or implies a new request. `bootstrap === undefined`
 * (not yet fetched) and `isLoading` both mean "loading". A settled
 * `authenticated` response with exactly one membership but no
 * `selectedTenantId` is treated as still-reconciling (loading), never as
 * a second, frontend-invented selection mechanism -- B2's server-side
 * auto-selection is authoritative and this state should not normally
 * outlive a single response.
 */
export function resolveAuthPhase(bootstrap: AuthBootstrap | undefined, isLoading: boolean): AuthPhase {
  if (isLoading || !bootstrap) return "loading";

  switch (bootstrap.status) {
    case "unauthenticated":
      return "unauthenticated";
    case "not_provisioned":
      return "not_provisioned";
    case "error":
      return "error";
    case "authenticated":
      if (bootstrap.memberships.length === 0) return "zero_memberships";
      if (!bootstrap.selectedTenantId) {
        return bootstrap.memberships.length === 1 ? "loading" : "needs_tenant_selection";
      }
      return "ready";
  }
}

export type RouteClass =
  | "login"
  | "select-tenant"
  | "access-denied"
  | "protected"
  | "platform-admin"
  | "sdk-auth"
  | "api"
  | "unclassified";

export function classifyRoute(pathname: string): RouteClass {
  if (pathname === "/login") return "login";
  if (pathname === "/select-tenant") return "select-tenant";
  if (pathname === "/access-denied") return "access-denied";
  if (pathname.startsWith("/auth/") || pathname.startsWith("/auth")) return "sdk-auth";
  if (pathname.startsWith("/api/") || pathname.startsWith("/api")) return "api";
  if (pathname === "/admin" || pathname.startsWith("/admin/")) return "platform-admin";
  if (pathname === "/" || pathname === "/farms" || pathname.startsWith("/farms/")) return "protected";
  return "unclassified";
}

export type RouteAccessDecision =
  | { kind: "loading" }
  | { kind: "allow" }
  | { kind: "redirect"; to: string }
  | { kind: "error" };

function loginRedirectFor(pathname: string, search: string): RouteAccessDecision {
  const returnTo = sanitizeReturnTo(`${pathname}${search}`);
  return { kind: "redirect", to: `/login?returnTo=${encodeURIComponent(returnTo)}` };
}

/**
 * The single decision point every gated route defers to. `sdk-auth`
 * (Auth0-owned /auth/*), `api` (server-side-secured, never page-gated),
 * and `unclassified` routes are always allowed through unconditionally
 * -- this model only ever governs CMP's own page routes.
 */
export function decideRouteAccess(params: {
  routeClass: RouteClass;
  phase: AuthPhase;
  pathname: string;
  search: string;
}): RouteAccessDecision {
  const { routeClass, phase, pathname, search } = params;

  if (routeClass === "sdk-auth" || routeClass === "api" || routeClass === "unclassified") {
    return { kind: "allow" };
  }

  if (phase === "loading") {
    return { kind: "loading" };
  }

  switch (routeClass) {
    case "protected":
      switch (phase) {
        case "ready":
          return { kind: "allow" };
        case "needs_tenant_selection":
          return { kind: "redirect", to: "/select-tenant" };
        case "zero_memberships":
        case "not_provisioned":
          return { kind: "redirect", to: "/access-denied" };
        case "unauthenticated":
          return loginRedirectFor(pathname, search);
        case "error":
          return { kind: "error" };
      }
      break;

    // Platform-level (PILOT-SETUP-001B3): authentication is all this model
    // gates -- whether the signed-in principal actually holds platform-admin
    // authority is a backend-only fact (`require_platform_admin`), never
    // knowable here (AuthBootstrap carries no platform-admin flag). Unlike
    // "protected", a real Platform Admin may legitimately have zero tenant
    // memberships and no tenant selected, so those phases still render this
    // route -- its own pages surface a 403 from the backend instead.
    case "platform-admin":
      switch (phase) {
        case "unauthenticated":
          return loginRedirectFor(pathname, search);
        case "not_provisioned":
          return { kind: "redirect", to: "/access-denied" };
        case "error":
          return { kind: "error" };
        default:
          return { kind: "allow" };
      }

    case "login":
      switch (phase) {
        case "unauthenticated":
          return { kind: "allow" };
        case "ready": {
          const requested = new URLSearchParams(search).get("returnTo");
          return { kind: "redirect", to: sanitizeReturnTo(requested) };
        }
        case "needs_tenant_selection":
          return { kind: "redirect", to: "/select-tenant" };
        case "zero_memberships":
        case "not_provisioned":
          return { kind: "redirect", to: "/access-denied" };
        case "error":
          return { kind: "error" };
      }
      break;

    case "select-tenant":
      switch (phase) {
        case "unauthenticated":
          return loginRedirectFor(pathname, search);
        case "zero_memberships":
        case "not_provisioned":
          return { kind: "redirect", to: "/access-denied" };
        case "error":
          return { kind: "error" };
        // "ready" and "needs_tenant_selection" both legitimately render
        // this page -- B2's own page already handles either correctly
        // (showing the picker regardless of a pre-existing selection).
        default:
          return { kind: "allow" };
      }

    case "access-denied":
      switch (phase) {
        case "unauthenticated":
          return loginRedirectFor(pathname, search);
        case "ready":
          return { kind: "redirect", to: "/farms" };
        case "needs_tenant_selection":
          return { kind: "redirect", to: "/select-tenant" };
        case "error":
          return { kind: "error" };
        // "zero_memberships" / "not_provisioned": this is the correct page.
        default:
          return { kind: "allow" };
      }
  }

  return { kind: "allow" };
}
