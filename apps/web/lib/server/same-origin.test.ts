// @vitest-environment node
import { NextRequest } from "next/server";
import { describe, expect, it } from "vitest";

import { isSameOriginRequest } from "@/lib/server/same-origin";

describe("isSameOriginRequest", () => {
  it("accepts a matching Origin", () => {
    const request = new NextRequest("http://localhost:3000/api/tenant/select", {
      headers: { origin: "http://localhost:3000" },
    });
    expect(isSameOriginRequest(request)).toBe(true);
  });

  it("rejects a cross-origin Origin", () => {
    const request = new NextRequest("http://localhost:3000/api/tenant/select", {
      headers: { origin: "https://evil.example" },
    });
    expect(isSameOriginRequest(request)).toBe(false);
  });

  it("rejects a same-hostname-different-port Origin (still a different origin)", () => {
    const request = new NextRequest("http://localhost:3000/api/tenant/select", {
      headers: { origin: "http://localhost:4000" },
    });
    expect(isSameOriginRequest(request)).toBe(false);
  });

  it("accepts a request with no Origin header (SameSite cookies remain the primary defense)", () => {
    const request = new NextRequest("http://localhost:3000/api/tenant/select");
    expect(isSameOriginRequest(request)).toBe(true);
  });

  it("rejects a malformed Origin header", () => {
    const request = new NextRequest("http://localhost:3000/api/tenant/select", {
      headers: { origin: "not a url" },
    });
    expect(isSameOriginRequest(request)).toBe(false);
  });
});
