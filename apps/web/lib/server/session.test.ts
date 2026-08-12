// @vitest-environment node
import { beforeEach, describe, expect, it, vi } from "vitest";

import { setAuth0ClientForTesting } from "@/lib/server/auth0";
import { getCmpApiAccessToken, SessionExpiredError } from "@/lib/server/session";

function fakeClient(overrides: Partial<Record<"getSession" | "getAccessToken", ReturnType<typeof vi.fn>>> = {}) {
  return {
    getSession: overrides.getSession ?? vi.fn(),
    getAccessToken: overrides.getAccessToken ?? vi.fn(),
  };
}

beforeEach(() => {
  setAuth0ClientForTesting(null);
});

describe("getCmpApiAccessToken", () => {
  it("calls the SDK's getAccessToken() with ZERO arguments (App Router overload) and returns only its token field", async () => {
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

    const token = await getCmpApiAccessToken();

    // Strict arity check: passing (request, cookieCarrier) here would
    // silently select the middleware/Pages Router overload instead
    // (AUTH-001C.1's root cause) -- this must fail if that regresses.
    expect(getAccessToken).toHaveBeenCalledWith();
    expect(getAccessToken.mock.calls[0]).toHaveLength(0);
    // This module's own getSession is never called on the way to a
    // token -- getAccessToken() is the sole, authoritative real-auth
    // check (AUTH-001C.2); no separate session precheck exists.
    expect(getSession).not.toHaveBeenCalled();
    expect(token).toBe("cmp-api-access-token");
    expect(token).not.toBe("session-cached-token-should-be-ignored");
    expect(token).not.toContain("id-token");
  });

  it("no session at all (SDK's own internal missing_session case) surfaces as SessionExpiredError, not a distinct code path", async () => {
    // Mirrors the real SDK: executeGetAccessToken() resolves the session
    // itself and throws AccessTokenError(MISSING_SESSION, ...) before
    // ever returning a token when there is no usable session -- CMP's
    // wrapper must treat that identically to any other getAccessToken
    // failure, since there is no separate getSession() precheck.
    const getAccessToken = vi
      .fn()
      .mockRejectedValue(Object.assign(new Error("The user does not have an active session."), { code: "missing_session" }));
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    setAuth0ClientForTesting(fakeClient({ getAccessToken }) as any);

    await expect(getCmpApiAccessToken()).rejects.toBeInstanceOf(SessionExpiredError);
  });

  it("wraps any getAccessToken failure into SessionExpiredError, without leaking the SDK message as the thrown message", async () => {
    const getAccessToken = vi.fn().mockRejectedValue(new Error("refresh_token_expired: some vendor-specific detail"));
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    setAuth0ClientForTesting(fakeClient({ getAccessToken }) as any);

    await expect(getCmpApiAccessToken()).rejects.toBeInstanceOf(SessionExpiredError);
    try {
      await getCmpApiAccessToken();
      expect.unreachable();
    } catch (err) {
      expect(err).toBeInstanceOf(SessionExpiredError);
      expect((err as SessionExpiredError).message).not.toMatch(/vendor-specific/);
      // The original cause is preserved for server-side logging only.
      expect(((err as SessionExpiredError).cause as Error).message).toMatch(/vendor-specific/);
    }
  });
});
