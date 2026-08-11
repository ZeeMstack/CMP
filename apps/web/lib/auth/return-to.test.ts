import { describe, expect, it } from "vitest";

import { RETURN_TO_FALLBACK, sanitizeReturnTo } from "@/lib/auth/return-to";

describe("sanitizeReturnTo", () => {
  it("accepts a plain local path", () => {
    expect(sanitizeReturnTo("/farms")).toBe("/farms");
  });

  it("accepts a local path with a segment and query string", () => {
    expect(sanitizeReturnTo("/farms/abc?x=1")).toBe("/farms/abc?x=1");
  });

  it("accepts a deep local path with multiple query params", () => {
    expect(sanitizeReturnTo("/farms/abc/crop-batches?state=active")).toBe("/farms/abc/crop-batches?state=active");
  });

  it("falls back on null/undefined/empty", () => {
    expect(sanitizeReturnTo(null)).toBe(RETURN_TO_FALLBACK);
    expect(sanitizeReturnTo(undefined)).toBe(RETURN_TO_FALLBACK);
    expect(sanitizeReturnTo("")).toBe(RETURN_TO_FALLBACK);
  });

  it("rejects an absolute external HTTPS URL", () => {
    expect(sanitizeReturnTo("https://evil.example")).toBe(RETURN_TO_FALLBACK);
    expect(sanitizeReturnTo("https://evil.example/farms")).toBe(RETURN_TO_FALLBACK);
  });

  it("rejects an absolute external HTTP URL", () => {
    expect(sanitizeReturnTo("http://evil.example")).toBe(RETURN_TO_FALLBACK);
  });

  it("rejects a protocol-relative URL", () => {
    expect(sanitizeReturnTo("//evil.example")).toBe(RETURN_TO_FALLBACK);
    expect(sanitizeReturnTo("///evil.example")).toBe(RETURN_TO_FALLBACK);
  });

  it("rejects a javascript: URL", () => {
    expect(sanitizeReturnTo("javascript:alert(1)")).toBe(RETURN_TO_FALLBACK);
  });

  it("rejects a data: URL", () => {
    expect(sanitizeReturnTo("data:text/html,<script>alert(1)</script>")).toBe(RETURN_TO_FALLBACK);
  });

  it("rejects a mailto: URL", () => {
    expect(sanitizeReturnTo("mailto:a@example.com")).toBe(RETURN_TO_FALLBACK);
  });

  it("rejects a path containing a literal backslash", () => {
    expect(sanitizeReturnTo("/\\evil.example")).toBe(RETURN_TO_FALLBACK);
    expect(sanitizeReturnTo("\\/evil.example")).toBe(RETURN_TO_FALLBACK);
  });

  it("rejects a URL-encoded trick that resolves to a protocol-relative URL after decoding", () => {
    expect(sanitizeReturnTo("%2F%2Fevil.example")).toBe(RETURN_TO_FALLBACK);
  });

  it("handles malformed percent-encoding safely (does not throw)", () => {
    expect(() => sanitizeReturnTo("%E0%A4%A")).not.toThrow();
    expect(sanitizeReturnTo("%E0%A4%A")).toBe(RETURN_TO_FALLBACK);
  });

  it("rejects /login (would create a redirect loop)", () => {
    expect(sanitizeReturnTo("/login")).toBe(RETURN_TO_FALLBACK);
    expect(sanitizeReturnTo("/login?returnTo=/farms")).toBe(RETURN_TO_FALLBACK);
  });

  it("rejects Auth0 SDK-owned routes", () => {
    expect(sanitizeReturnTo("/auth/login")).toBe(RETURN_TO_FALLBACK);
    expect(sanitizeReturnTo("/auth/logout")).toBe(RETURN_TO_FALLBACK);
    expect(sanitizeReturnTo("/auth/callback")).toBe(RETURN_TO_FALLBACK);
    expect(sanitizeReturnTo("/auth/anything-else")).toBe(RETURN_TO_FALLBACK);
  });

  it("rejects API routes", () => {
    expect(sanitizeReturnTo("/api/farms")).toBe(RETURN_TO_FALLBACK);
    expect(sanitizeReturnTo("/api/auth/bootstrap")).toBe(RETURN_TO_FALLBACK);
  });

  it("the fallback is always /farms", () => {
    expect(RETURN_TO_FALLBACK).toBe("/farms");
  });
});
