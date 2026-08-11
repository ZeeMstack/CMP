import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  registerSessionRecoveryHandler,
  resetSessionRecoveryDedupe,
  resetSessionRecoveryForTesting,
  triggerSessionRecovery,
} from "@/lib/auth/sessionRecovery";

beforeEach(() => {
  resetSessionRecoveryForTesting();
});

afterEach(() => {
  resetSessionRecoveryForTesting();
});

describe("sessionRecovery", () => {
  it("calls the registered handler with the given returnTo path", () => {
    const handler = vi.fn();
    registerSessionRecoveryHandler(handler);

    triggerSessionRecovery("/farms/abc");

    expect(handler).toHaveBeenCalledWith("/farms/abc");
  });

  it("does nothing if no handler is registered (never throws)", () => {
    expect(() => triggerSessionRecovery("/farms/abc")).not.toThrow();
  });

  it("deduplicates: a burst of concurrent triggers calls the handler exactly once", () => {
    const handler = vi.fn();
    registerSessionRecoveryHandler(handler);

    triggerSessionRecovery("/farms/abc");
    triggerSessionRecovery("/farms/abc");
    triggerSessionRecovery("/farms/def");
    triggerSessionRecovery("/farms/ghi");

    expect(handler).toHaveBeenCalledTimes(1);
    expect(handler).toHaveBeenCalledWith("/farms/abc"); // the first one wins
  });

  it("resetSessionRecoveryDedupe allows a subsequent, genuinely new recovery to trigger again", () => {
    const handler = vi.fn();
    registerSessionRecoveryHandler(handler);

    triggerSessionRecovery("/farms/abc");
    expect(handler).toHaveBeenCalledTimes(1);

    resetSessionRecoveryDedupe();
    triggerSessionRecovery("/farms/xyz");

    expect(handler).toHaveBeenCalledTimes(2);
    expect(handler).toHaveBeenLastCalledWith("/farms/xyz");
  });

  it("unregistering the handler (null) stops further calls without throwing", () => {
    const handler = vi.fn();
    registerSessionRecoveryHandler(handler);
    registerSessionRecoveryHandler(null);

    expect(() => triggerSessionRecovery("/farms/abc")).not.toThrow();
    expect(handler).not.toHaveBeenCalled();
  });
});
