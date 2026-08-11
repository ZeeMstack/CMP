import { describe, expect, it } from "vitest";

import { AppError } from "@/lib/errors/adapter";
import { shouldRetryQuery } from "@/lib/query/retry";

describe("shouldRetryQuery", () => {
  it("never retries a 400", () => {
    expect(shouldRetryQuery(0, new AppError("invalid_request", "bad", 400))).toBe(false);
  });

  it("never retries a 401", () => {
    expect(shouldRetryQuery(0, new AppError("identity_error", "no", 401))).toBe(false);
  });

  it("never retries a 403", () => {
    expect(shouldRetryQuery(0, new AppError("permission_error", "no", 403))).toBe(false);
  });

  it("never retries a 404", () => {
    expect(shouldRetryQuery(0, new AppError("not_found", "no", 404))).toBe(false);
  });

  it("never retries a 409", () => {
    expect(shouldRetryQuery(0, new AppError("conflict", "no", 409))).toBe(false);
  });

  it("retries a 5xx (via network_error) up to the bounded limit", () => {
    const err = new AppError("network_error", "bad gateway", 502);
    expect(shouldRetryQuery(0, err)).toBe(true);
    expect(shouldRetryQuery(1, err)).toBe(true);
    expect(shouldRetryQuery(2, err)).toBe(true);
    expect(shouldRetryQuery(3, err)).toBe(false);
  });

  it("retries a network failure with no status (status: null) up to the bounded limit", () => {
    const err = new AppError("network_error", "offline");
    expect(err.status).toBeNull();
    expect(shouldRetryQuery(0, err)).toBe(true);
    expect(shouldRetryQuery(3, err)).toBe(false);
  });

  it("retries a non-AppError (unexpected thrown value) up to the bounded limit, never indefinitely", () => {
    expect(shouldRetryQuery(0, new Error("boom"))).toBe(true);
    expect(shouldRetryQuery(3, new Error("boom"))).toBe(false);
  });
});
