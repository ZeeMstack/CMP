import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/auth/sessionRecovery", () => ({
  triggerSessionRecovery: vi.fn(),
}));

import { listFarms } from "@/lib/api/client";
import { triggerSessionRecovery } from "@/lib/auth/sessionRecovery";
import { AppError } from "@/lib/errors/adapter";

const mockTriggerSessionRecovery = vi.mocked(triggerSessionRecovery);

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
  mockTriggerSessionRecovery.mockReset();
  window.history.replaceState(null, "", "/farms/abc?state=active");
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

describe("lib/api/client 401 recovery wiring", () => {
  it("triggers session recovery on a bare 401", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ detail: "no" }, 401));

    await expect(listFarms()).rejects.toBeInstanceOf(AppError);

    expect(mockTriggerSessionRecovery).toHaveBeenCalledTimes(1);
  });

  it("triggers session recovery on the BFF's {\"error\":\"session_expired\"} 401 body identically", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ error: "session_expired" }, 401));

    await expect(listFarms()).rejects.toBeInstanceOf(AppError);

    expect(mockTriggerSessionRecovery).toHaveBeenCalledTimes(1);
  });

  it("passes the current page path + query as the returnTo candidate", async () => {
    fetchMock.mockResolvedValue(jsonResponse({}, 401));

    await expect(listFarms()).rejects.toBeInstanceOf(AppError);

    expect(mockTriggerSessionRecovery).toHaveBeenCalledWith("/farms/abc?state=active");
  });

  it("still throws the mapped AppError so the calling useQuery enters its own error state", async () => {
    fetchMock.mockResolvedValue(jsonResponse({}, 401));

    await expect(listFarms()).rejects.toMatchObject({ kind: "identity_error", status: 401 });
  });

  it("does NOT trigger session recovery on 403 (permission error, not an auth failure)", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ detail: "no" }, 403));

    await expect(listFarms()).rejects.toMatchObject({ kind: "permission_error" });
    expect(mockTriggerSessionRecovery).not.toHaveBeenCalled();
  });

  it("does NOT trigger session recovery on 404 (not found, unrelated to auth)", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ detail: "not found" }, 404));

    await expect(listFarms()).rejects.toMatchObject({ kind: "not_found" });
    expect(mockTriggerSessionRecovery).not.toHaveBeenCalled();
  });

  it("does NOT trigger session recovery on a successful response", async () => {
    fetchMock.mockResolvedValue(jsonResponse([]));

    await listFarms();

    expect(mockTriggerSessionRecovery).not.toHaveBeenCalled();
  });

  it("does NOT trigger session recovery on a network failure (not a 401)", async () => {
    fetchMock.mockRejectedValue(new Error("ECONNREFUSED"));

    await expect(listFarms()).rejects.toBeInstanceOf(AppError);
    expect(mockTriggerSessionRecovery).not.toHaveBeenCalled();
  });
});
