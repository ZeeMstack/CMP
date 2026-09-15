import { afterEach, describe, expect, it } from "vitest";

import {
  clearWorkingLocationStorage,
  readWorkingLocation,
  WORKING_LOCATION_STORAGE_KEY,
  WORKING_LOCATION_TTL_MS,
  writeWorkingLocation,
} from "./workingLocation";

afterEach(() => {
  window.localStorage.clear();
});

describe("workingLocation storage helper", () => {
  it("returns null when nothing has been stored", () => {
    expect(readWorkingLocation()).toBeNull();
  });

  it("stores structured identity, not just a display string", () => {
    const now = new Date("2026-01-01T08:00:00Z");
    writeWorkingLocation({ locationId: "loc-1", farmId: "farm-1", code: "T07", pathString: "GH-01 / Zone 2 / Span 4 / Table 07" }, now);

    const raw = window.localStorage.getItem(WORKING_LOCATION_STORAGE_KEY);
    expect(raw).not.toBeNull();
    const parsed = JSON.parse(raw as string);
    expect(parsed).toMatchObject({
      locationId: "loc-1",
      farmId: "farm-1",
      code: "T07",
      pathString: "GH-01 / Zone 2 / Span 4 / Table 07",
    });
    expect(typeof parsed.selectedAt).toBe("string");
    expect(typeof parsed.expiresAt).toBe("string");
  });

  it("reads back exactly what was written while still within its expiry window", () => {
    const now = new Date("2026-01-01T08:00:00Z");
    writeWorkingLocation({ locationId: "loc-1", farmId: "farm-1", code: "T07", pathString: "GH-01 / Table 07" }, now);

    const read = readWorkingLocation(new Date(now.getTime() + 1000));
    expect(read).toMatchObject({ locationId: "loc-1", farmId: "farm-1" });
  });

  it("uses a bounded 12-hour expiry", () => {
    expect(WORKING_LOCATION_TTL_MS).toBe(12 * 60 * 60 * 1000);
  });

  it("treats an expired working location as absent and cleans it up automatically", () => {
    const now = new Date("2026-01-01T08:00:00Z");
    writeWorkingLocation({ locationId: "loc-1", farmId: "farm-1", code: "T07", pathString: "GH-01 / Table 07" }, now);

    const justAfterExpiry = new Date(now.getTime() + WORKING_LOCATION_TTL_MS + 1);
    expect(readWorkingLocation(justAfterExpiry)).toBeNull();
    // Cleaned up automatically -- the raw key no longer lingers in storage.
    expect(window.localStorage.getItem(WORKING_LOCATION_STORAGE_KEY)).toBeNull();
  });

  it("does not expire one millisecond before the 12-hour boundary", () => {
    const now = new Date("2026-01-01T08:00:00Z");
    writeWorkingLocation({ locationId: "loc-1", farmId: "farm-1", code: "T07", pathString: "GH-01 / Table 07" }, now);

    const justBeforeExpiry = new Date(now.getTime() + WORKING_LOCATION_TTL_MS - 1);
    expect(readWorkingLocation(justBeforeExpiry)).not.toBeNull();
  });

  it("Clear removes the working location entirely", () => {
    writeWorkingLocation({ locationId: "loc-1", farmId: "farm-1", code: "T07", pathString: "GH-01 / Table 07" });
    clearWorkingLocationStorage();
    expect(readWorkingLocation()).toBeNull();
  });

  it("treats corrupted stored JSON as absent rather than throwing", () => {
    window.localStorage.setItem(WORKING_LOCATION_STORAGE_KEY, "{not json");
    expect(readWorkingLocation()).toBeNull();
  });

  it("a later write fully replaces an earlier one, never merging", () => {
    writeWorkingLocation({ locationId: "loc-1", farmId: "farm-1", code: "T07", pathString: "GH-01 / Table 07" });
    writeWorkingLocation({ locationId: "loc-2", farmId: "farm-1", code: "T08", pathString: "GH-01 / Table 08" });

    const read = readWorkingLocation();
    expect(read?.locationId).toBe("loc-2");
    expect(read?.code).toBe("T08");
  });
});
