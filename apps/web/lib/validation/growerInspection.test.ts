import { describe, expect, it } from "vitest";

import { validateAffectedWithinInspected } from "./growerInspection";

describe("validateAffectedWithinInspected", () => {
  it("blocks affected count exceeding inspected count", () => {
    expect(validateAffectedWithinInspected(10, 11)).toBe("Affected count cannot exceed inspected count.");
  });

  it("allows affected count equal to inspected count", () => {
    expect(validateAffectedWithinInspected(10, 10)).toBeNull();
  });

  it("allows affected count below inspected count", () => {
    expect(validateAffectedWithinInspected(10, 3)).toBeNull();
  });

  it("skips the check when either count is not recorded", () => {
    expect(validateAffectedWithinInspected(null, 5)).toBeNull();
    expect(validateAffectedWithinInspected(10, null)).toBeNull();
    expect(validateAffectedWithinInspected(null, null)).toBeNull();
  });
});
