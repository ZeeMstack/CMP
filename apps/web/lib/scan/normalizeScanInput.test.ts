import { describe, expect, it } from "vitest";

import { GROWCMP_PRODUCTION_ORIGIN, normalizeScanInput } from "./normalizeScanInput";

const DEV_ORIGIN = "http://localhost:3000";
const ALLOWED_ORIGINS = [DEV_ORIGIN, GROWCMP_PRODUCTION_ORIGIN];

describe("normalizeScanInput", () => {
  it("accepts a raw QR token", () => {
    expect(normalizeScanInput("tok-abc123", ALLOWED_ORIGINS)).toEqual({ token: "tok-abc123" });
  });

  it("trims surrounding whitespace from a raw token", () => {
    expect(normalizeScanInput("  tok-abc123  ", ALLOWED_ORIGINS)).toEqual({ token: "tok-abc123" });
  });

  it("extracts the token from a full GrowCMP production scan URL", () => {
    expect(normalizeScanInput(`${GROWCMP_PRODUCTION_ORIGIN}/q/tok-abc123`, ALLOWED_ORIGINS)).toEqual({
      token: "tok-abc123",
    });
  });

  it("extracts the token from a scan URL on the current/allowed application origin (dev/test)", () => {
    expect(normalizeScanInput(`${DEV_ORIGIN}/q/tok-abc123`, ALLOWED_ORIGINS)).toEqual({ token: "tok-abc123" });
  });

  it("tolerates a trailing slash on the scan URL path", () => {
    expect(normalizeScanInput(`${GROWCMP_PRODUCTION_ORIGIN}/q/tok-abc123/`, ALLOWED_ORIGINS)).toEqual({
      token: "tok-abc123",
    });
  });

  it("rejects blank input", () => {
    expect(normalizeScanInput("", ALLOWED_ORIGINS)).toEqual({ error: expect.any(String) });
    expect(normalizeScanInput("   ", ALLOWED_ORIGINS)).toEqual({ error: expect.any(String) });
  });

  it("rejects a third-party absolute URL even though its path is exactly /q/<token>", () => {
    const result = normalizeScanInput("https://evil.example/q/tok-abc123", ALLOWED_ORIGINS);
    expect("error" in result).toBe(true);
  });

  it("rejects a third-party origin regardless of which origins happen to be allowed elsewhere", () => {
    const result = normalizeScanInput("https://phishing-site.com/q/tok-abc123", [GROWCMP_PRODUCTION_ORIGIN]);
    expect("error" in result).toBe(true);
  });

  it("rejects a well-formed URL on a trusted origin whose path is not a scan link", () => {
    const result = normalizeScanInput(`${GROWCMP_PRODUCTION_ORIGIN}/farms/farm-1`, ALLOWED_ORIGINS);
    expect("error" in result).toBe(true);
  });

  it("rejects a URL with extra path segments beyond the token", () => {
    const result = normalizeScanInput(`${GROWCMP_PRODUCTION_ORIGIN}/q/tok-abc/extra`, ALLOWED_ORIGINS);
    expect("error" in result).toBe(true);
  });

  it("rejects a malformed URL-shaped string that isn't a real URL and isn't a valid token", () => {
    const result = normalizeScanInput("http://", ALLOWED_ORIGINS);
    expect("error" in result).toBe(true);
  });

  it("rejects a token containing characters outside the token charset", () => {
    const result = normalizeScanInput("tok abc!", ALLOWED_ORIGINS);
    expect("error" in result).toBe(true);
  });

  it("never returns a navigable URL -- only ever a bare token or an error, for any input including a rejected third-party URL", () => {
    const inputs = [
      "tok-abc123",
      `${GROWCMP_PRODUCTION_ORIGIN}/q/tok-abc123`,
      "https://evil.example.com/phishing",
      "https://evil.example.com/q/tok-abc123",
      "javascript:alert(1)",
    ];
    for (const input of inputs) {
      const result = normalizeScanInput(input, ALLOWED_ORIGINS);
      if ("token" in result) {
        expect(result.token).not.toMatch(/^[a-z]+:\/\//i);
        expect(result.token).not.toContain("/");
      }
    }
  });
});
