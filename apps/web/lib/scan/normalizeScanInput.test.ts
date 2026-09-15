import { describe, expect, it } from "vitest";

import { normalizeScanInput } from "./normalizeScanInput";

describe("normalizeScanInput", () => {
  it("accepts a raw QR token", () => {
    expect(normalizeScanInput("tok-abc123")).toEqual({ token: "tok-abc123" });
  });

  it("trims surrounding whitespace from a raw token", () => {
    expect(normalizeScanInput("  tok-abc123  ")).toEqual({ token: "tok-abc123" });
  });

  it("extracts the token from a full GrowCMP scan URL", () => {
    expect(normalizeScanInput("https://growcmp.com/q/tok-abc123")).toEqual({ token: "tok-abc123" });
  });

  it("extracts the token from a scan URL on another legitimate deployment origin (preview/LAN/localhost)", () => {
    expect(normalizeScanInput("http://localhost:3000/q/tok-abc123")).toEqual({ token: "tok-abc123" });
  });

  it("tolerates a trailing slash on the scan URL path", () => {
    expect(normalizeScanInput("https://growcmp.com/q/tok-abc123/")).toEqual({ token: "tok-abc123" });
  });

  it("rejects blank input", () => {
    expect(normalizeScanInput("")).toEqual({ error: expect.any(String) });
    expect(normalizeScanInput("   ")).toEqual({ error: expect.any(String) });
  });

  it("rejects a well-formed URL whose path is not a scan link", () => {
    const result = normalizeScanInput("https://growcmp.com/farms/farm-1");
    expect("error" in result).toBe(true);
  });

  it("rejects a URL with extra path segments beyond the token", () => {
    const result = normalizeScanInput("https://growcmp.com/q/tok-abc/extra");
    expect("error" in result).toBe(true);
  });

  it("rejects a token containing characters outside the token charset", () => {
    const result = normalizeScanInput("tok abc!");
    expect("error" in result).toBe(true);
  });

  it("never returns a navigable URL -- only ever a bare token or an error, for any input including an arbitrary external URL", () => {
    const inputs = [
      "tok-abc123",
      "https://growcmp.com/q/tok-abc123",
      "https://evil.example.com/phishing",
      "javascript:alert(1)",
    ];
    for (const input of inputs) {
      const result = normalizeScanInput(input);
      if ("token" in result) {
        expect(result.token).not.toMatch(/^[a-z]+:\/\//i);
        expect(result.token).not.toContain("/");
      }
    }
  });
});
