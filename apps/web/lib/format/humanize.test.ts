import { describe, expect, it } from "vitest";

import { humanizeEnumCode } from "./humanize";

describe("humanizeEnumCode", () => {
  it("humanizes a single-word code", () => {
    expect(humanizeEnumCode("ROOT")).toBe("Root");
  });

  it("humanizes a multi-word underscore code", () => {
    expect(humanizeEnumCode("NUTRIENT_DEFICIENCY")).toBe("Nutrient deficiency");
    expect(humanizeEnumCode("PEST_SIGHTING")).toBe("Pest sighting");
  });

  it("works generically for an unknown future code with many words", () => {
    expect(humanizeEnumCode("SOME_BRAND_NEW_UNSEEN_REASON_CODE")).toBe("Some brand new unseen reason code");
  });

  it("defensively normalizes already-lowercase or mixed-case input", () => {
    expect(humanizeEnumCode("already_lowercase")).toBe("Already lowercase");
    expect(humanizeEnumCode("Mixed_Case_Value")).toBe("Mixed case value");
  });

  it("returns an empty string for null/undefined/empty input", () => {
    expect(humanizeEnumCode(null)).toBe("");
    expect(humanizeEnumCode(undefined)).toBe("");
    expect(humanizeEnumCode("")).toBe("");
  });

  it("collapses stray whitespace/underscores defensively", () => {
    expect(humanizeEnumCode("  PEST__SIGHTING  ")).toBe("Pest sighting");
  });
});
