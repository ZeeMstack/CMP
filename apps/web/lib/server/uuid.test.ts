import { describe, expect, it } from "vitest";

import { isValidUuid } from "@/lib/server/uuid";

describe("isValidUuid", () => {
  it("accepts a well-formed v4-shaped UUID", () => {
    expect(isValidUuid("11111111-1111-1111-1111-111111111111")).toBe(true);
  });

  it("accepts uppercase hex", () => {
    expect(isValidUuid("AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE")).toBe(true);
  });

  it("rejects a malformed string", () => {
    expect(isValidUuid("not-a-uuid")).toBe(false);
  });

  it("rejects a UUID missing a segment", () => {
    expect(isValidUuid("11111111-1111-1111-111111111111")).toBe(false);
  });

  it("rejects non-string values", () => {
    expect(isValidUuid(12345)).toBe(false);
    expect(isValidUuid(null)).toBe(false);
    expect(isValidUuid(undefined)).toBe(false);
    expect(isValidUuid({})).toBe(false);
  });

  it("rejects an empty string", () => {
    expect(isValidUuid("")).toBe(false);
  });
});
