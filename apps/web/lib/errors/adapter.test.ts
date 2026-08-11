import { describe, expect, it } from "vitest";

import { AppError, ERROR_KIND_COPY, errorFromNetworkFailure, errorFromResponse } from "./adapter";

describe("errorFromResponse", () => {
  it("maps 401 to identity_error", () => {
    expect(errorFromResponse(401).kind).toBe("identity_error");
  });

  it("maps 403 to permission_error, distinct from identity_error", () => {
    expect(errorFromResponse(403).kind).toBe("permission_error");
    expect(errorFromResponse(403).kind).not.toBe(errorFromResponse(401).kind);
  });

  it("403's default message describes access, not identity/session/network", () => {
    const message = errorFromResponse(403).message;
    expect(message).not.toMatch(/sign in again/i);
    expect(message).not.toMatch(/session expired/i);
    expect(message).not.toMatch(/network/i);
  });

  it("404 remains not_found even for a resource a 403 could plausibly apply to (cross-tenant concealment preserved)", () => {
    expect(errorFromResponse(404).kind).toBe("not_found");
    expect(errorFromResponse(404).kind).not.toBe("permission_error");
  });

  it("maps 404 to not_found", () => {
    expect(errorFromResponse(404).kind).toBe("not_found");
  });

  it("maps 400 and 422 to invalid_request", () => {
    expect(errorFromResponse(400).kind).toBe("invalid_request");
    expect(errorFromResponse(422).kind).toBe("invalid_request");
  });

  it("maps 409 to conflict", () => {
    expect(errorFromResponse(409).kind).toBe("conflict");
  });

  it("maps 502 to network_error", () => {
    expect(errorFromResponse(502).kind).toBe("network_error");
  });

  it("maps other 5xx to server_error", () => {
    expect(errorFromResponse(500).kind).toBe("server_error");
    expect(errorFromResponse(503).kind).toBe("server_error");
  });

  it("preserves a provided detail message", () => {
    expect(errorFromResponse(404, "Farm not found").message).toBe("Farm not found");
  });

  it("preserves the original status", () => {
    expect(errorFromResponse(404).status).toBe(404);
  });
});

describe("ERROR_KIND_COPY: permission_error", () => {
  it("has copy distinct from identity_error, network_error, and server_error", () => {
    const permission = ERROR_KIND_COPY.permission_error;
    const identity = ERROR_KIND_COPY.identity_error;
    const network = ERROR_KIND_COPY.network_error;
    const server = ERROR_KIND_COPY.server_error;

    expect(permission).not.toEqual(identity);
    expect(permission.title).not.toMatch(/sign in|session/i);
    expect(permission.action).not.toMatch(/sign in|session expired/i);
    expect(permission).not.toEqual(network);
    expect(permission).not.toEqual(server);
  });
});

describe("errorFromNetworkFailure", () => {
  it("produces a network_error AppError", () => {
    const err = errorFromNetworkFailure(new Error("fetch failed"));
    expect(err).toBeInstanceOf(AppError);
    expect(err.kind).toBe("network_error");
    expect(err.message).toBe("fetch failed");
  });

  it("handles a non-Error cause", () => {
    const err = errorFromNetworkFailure("boom");
    expect(err.kind).toBe("network_error");
    expect(err.message).toBe("Network request failed.");
  });
});
