import { QueryClient } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { performSignOut } from "@/lib/auth/logout";

const PROD_ORIGIN = "https://growcmp-web.onrender.com";

let fetchMock: ReturnType<typeof vi.fn>;
let assignSpy: ReturnType<typeof vi.fn>;
const originalLocation = window.location;

function jsonResponse(body: unknown) {
  return new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } });
}

beforeEach(() => {
  // Matches the real /api/auth/logout route's shape (see route.ts): the
  // server resolves the absolute post-logout target from the trusted app
  // origin (APP_BASE_URL in production) and hands it back to the client.
  fetchMock = vi.fn().mockResolvedValue(jsonResponse({ ok: true, postLogoutRedirectUri: `${PROD_ORIGIN}/login` }));
  vi.stubGlobal("fetch", fetchMock);

  // jsdom's window.location.assign is not spy-able in place (non-
  // configurable) -- replace the whole object, matching the standard
  // workaround for this jsdom limitation.
  assignSpy = vi.fn();
  Object.defineProperty(window, "location", {
    configurable: true,
    value: { ...originalLocation, assign: assignSpy },
  });
});

afterEach(() => {
  vi.unstubAllGlobals();
  Object.defineProperty(window, "location", { configurable: true, value: originalLocation });
});

describe("performSignOut", () => {
  it("clears the QueryClient cache", async () => {
    const queryClient = new QueryClient();
    queryClient.setQueryData(["auth", "bootstrap"], { status: "authenticated" });
    const clearSpy = vi.spyOn(queryClient, "clear");

    await performSignOut(queryClient);

    expect(clearSpy).toHaveBeenCalledTimes(1);
    expect(queryClient.getQueryData(["auth", "bootstrap"])).toBeUndefined();
  });

  it("POSTs to /api/auth/logout for CMP-owned cookie cleanup", async () => {
    const queryClient = new QueryClient();

    await performSignOut(queryClient);

    expect(fetchMock).toHaveBeenCalledWith("/api/auth/logout", { method: "POST" });
  });

  it("cleanup failure is best-effort: does not throw and still hands off to SDK logout with an absolute returnTo", async () => {
    fetchMock.mockRejectedValue(new Error("network down"));
    const queryClient = new QueryClient();

    await expect(performSignOut(queryClient)).resolves.toBeUndefined();

    // No server response to source postLogoutRedirectUri from -- falls
    // back to this same browser's own origin, never a relative path.
    const expected = new URL("/login", originalLocation.origin).toString();
    expect(assignSpy).toHaveBeenCalledWith(`/auth/logout?returnTo=${encodeURIComponent(expected)}`);
  });

  it("falls back to the browser's own origin if the cleanup response body is unparseable", async () => {
    fetchMock.mockResolvedValue(new Response("not json", { status: 200 }));
    const queryClient = new QueryClient();

    await performSignOut(queryClient);

    const expected = new URL("/login", originalLocation.origin).toString();
    expect(assignSpy).toHaveBeenCalledWith(`/auth/logout?returnTo=${encodeURIComponent(expected)}`);
  });

  it("hands off to the SDK-owned /auth/logout route with an ABSOLUTE returnTo (LIVE-ACCEPTANCE-HOTFIX-001)", async () => {
    const queryClient = new QueryClient();

    await performSignOut(queryClient);

    expect(assignSpy).toHaveBeenCalledTimes(1);
    const [target] = assignSpy.mock.calls[0] as [string];
    const returnTo = new URL(target, originalLocation.origin).searchParams.get("returnTo");

    expect(returnTo).toBe(`${PROD_ORIGIN}/login`);
    // 1. absolute
    expect(() => new URL(returnTo!)).not.toThrow();
    // 2. /login is preserved
    expect(new URL(returnTo!).pathname).toBe("/login");
    // 3. the configured (server-resolved) app origin is used, not this
    //    test's own jsdom origin
    expect(new URL(returnTo!).origin).toBe(PROD_ORIGIN);
  });

  it("uses the postLogoutRedirectUri exactly as resolved by the server -- never appends/derives from this page's own location", async () => {
    const queryClient = new QueryClient();

    await performSignOut(queryClient);

    expect(assignSpy).toHaveBeenCalledWith(`/auth/logout?returnTo=${encodeURIComponent(`${PROD_ORIGIN}/login`)}`);
  });

  it("does not introduce an open redirect: a malicious postLogoutRedirectUri in the response is passed through as an opaque query value, never used to navigate directly", async () => {
    // Defense in depth -- even if something upstream were compromised and
    // returned an attacker-controlled absolute URL, performSignOut itself
    // never navigates anywhere but the fixed, same-origin "/auth/logout"
    // path; the value only ever becomes the returnTo query parameter that
    // the SDK's own logout handler (and, downstream, Auth0's Allowed
    // Logout URLs allow-list) is responsible for validating.
    fetchMock.mockResolvedValue(jsonResponse({ ok: true, postLogoutRedirectUri: "https://evil.example/steal" }));
    const queryClient = new QueryClient();

    await performSignOut(queryClient);

    const [target] = assignSpy.mock.calls[0] as [string];
    expect(target.startsWith("/auth/logout?returnTo=")).toBe(true);
  });

  it("clears the cache and attempts cleanup BEFORE handing off to SDK logout (correct ordering)", async () => {
    const queryClient = new QueryClient();
    const clearSpy = vi.spyOn(queryClient, "clear");
    const callOrder: string[] = [];
    clearSpy.mockImplementation(() => callOrder.push("clear"));
    fetchMock.mockImplementation(async () => {
      callOrder.push("fetch");
      return new Response(null, { status: 200 });
    });
    assignSpy.mockImplementation(() => {
      callOrder.push("assign");
    });

    await performSignOut(queryClient);

    expect(callOrder).toEqual(["clear", "fetch", "assign"]);
  });

  it("never manipulates document.cookie directly (no Auth0-owned cookie handling in CMP code)", async () => {
    const cookieSetter = vi.fn();
    Object.defineProperty(document, "cookie", {
      configurable: true,
      set: cookieSetter,
      get: () => "",
    });

    const queryClient = new QueryClient();
    await performSignOut(queryClient);

    expect(cookieSetter).not.toHaveBeenCalled();
  });
});
