import { QueryClient } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { performSignOut } from "@/lib/auth/logout";

let fetchMock: ReturnType<typeof vi.fn>;
let assignSpy: ReturnType<typeof vi.fn>;
const originalLocation = window.location;

beforeEach(() => {
  fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 200 }));
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

  it("cleanup failure is best-effort: does not throw and still hands off to SDK logout", async () => {
    fetchMock.mockRejectedValue(new Error("network down"));
    const queryClient = new QueryClient();

    await expect(performSignOut(queryClient)).resolves.toBeUndefined();

    expect(assignSpy).toHaveBeenCalledWith("/auth/logout?returnTo=/login");
  });

  it("hands off to the SDK-owned /auth/logout route with returnTo=/login", async () => {
    const queryClient = new QueryClient();

    await performSignOut(queryClient);

    expect(assignSpy).toHaveBeenCalledTimes(1);
    expect(assignSpy).toHaveBeenCalledWith("/auth/logout?returnTo=/login");
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
