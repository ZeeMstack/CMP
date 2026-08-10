// @vitest-environment node
import type { NextRequest, NextResponse } from "next/server";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { setAuth0ClientForTesting } from "@/lib/server/auth0";
import { getAuthenticatedSession, getCmpApiAccessToken, SessionExpiredError } from "@/lib/server/session";

const fakeRequest = {} as NextRequest;
const fakeResponse = {} as NextResponse;

function fakeClient(overrides: Partial<Record<"getSession" | "getAccessToken", ReturnType<typeof vi.fn>>> = {}) {
  return {
    getSession: overrides.getSession ?? vi.fn(),
    getAccessToken: overrides.getAccessToken ?? vi.fn(),
  };
}

beforeEach(() => {
  setAuth0ClientForTesting(null);
});

describe("getAuthenticatedSession", () => {
  it("delegates to the Auth0 client's getSession(request) and returns it verbatim", async () => {
    const session = { user: { sub: "auth0|abc" }, tokenSet: { accessToken: "irrelevant" } };
    const getSession = vi.fn().mockResolvedValue(session);
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    setAuth0ClientForTesting(fakeClient({ getSession }) as any);

    const result = await getAuthenticatedSession(fakeRequest);

    expect(getSession).toHaveBeenCalledWith(fakeRequest);
    expect(result).toBe(session);
  });

  it("returns null when there is no session, without throwing", async () => {
    const getSession = vi.fn().mockResolvedValue(null);
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    setAuth0ClientForTesting(fakeClient({ getSession }) as any);

    await expect(getAuthenticatedSession(fakeRequest)).resolves.toBeNull();
  });
});

describe("getCmpApiAccessToken", () => {
  it("forwards request/cookieCarrier to getAccessToken and returns only its token field", async () => {
    const getAccessToken = vi.fn().mockResolvedValue({
      token: "cmp-api-access-token",
      expiresAt: 9999999999,
      audience: "https://cmp-api.example",
    });
    // A session whose id/access tokens differ from the getAccessToken()
    // result -- proves the wrapper never sources the forwarded value from
    // anywhere else (e.g. tokenSet.idToken or tokenSet.accessToken read
    // directly off the session).
    const getSession = vi.fn().mockResolvedValue({
      user: { sub: "auth0|abc" },
      tokenSet: { accessToken: "session-cached-token-should-be-ignored", idToken: "id-token-must-never-be-used" },
    });
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    setAuth0ClientForTesting(fakeClient({ getAccessToken, getSession }) as any);

    const token = await getCmpApiAccessToken(fakeRequest, fakeResponse);

    expect(getAccessToken).toHaveBeenCalledWith(fakeRequest, fakeResponse);
    expect(token).toBe("cmp-api-access-token");
    expect(token).not.toBe("session-cached-token-should-be-ignored");
    expect(token).not.toContain("id-token");
  });

  it("wraps any getAccessToken failure into SessionExpiredError, without leaking the SDK message as the thrown message", async () => {
    const getAccessToken = vi.fn().mockRejectedValue(new Error("refresh_token_expired: some vendor-specific detail"));
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    setAuth0ClientForTesting(fakeClient({ getAccessToken }) as any);

    await expect(getCmpApiAccessToken(fakeRequest, fakeResponse)).rejects.toBeInstanceOf(SessionExpiredError);
    try {
      await getCmpApiAccessToken(fakeRequest, fakeResponse);
      expect.unreachable();
    } catch (err) {
      expect(err).toBeInstanceOf(SessionExpiredError);
      expect((err as SessionExpiredError).message).not.toMatch(/vendor-specific/);
      // The original cause is preserved for server-side logging only.
      expect(((err as SessionExpiredError).cause as Error).message).toMatch(/vendor-specific/);
    }
  });
});
