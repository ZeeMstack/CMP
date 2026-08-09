import { describe, expect, it } from "vitest";

import { AppError, errorFromNetworkFailure, errorFromResponse } from "./adapter";

describe("errorFromResponse", () => {
  it("maps 401 to identity_error", () => {
    expect(errorFromResponse(401).kind).toBe("identity_error");
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
