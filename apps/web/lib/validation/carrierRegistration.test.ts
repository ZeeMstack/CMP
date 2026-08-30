import { describe, expect, it } from "vitest";

import {
  DEFAULT_CARRIER_REGISTRATION_FORM_VALUES,
  LEGACY_GENERIC_CARRIER_TYPE_CODE,
  MAX_BULK_CARRIERS,
  buildCarrierBulkCreatePayload,
  buildCarrierCreatePayload,
  carrierRegistrationFormSchema,
  generateCarrierCodePreview,
  isSelectableForCarrierRegistration,
} from "./carrierRegistration";

describe("isSelectableForCarrierRegistration", () => {
  it("excludes the legacy generic cultivation_plate type", () => {
    expect(isSelectableForCarrierRegistration({ status: "active", carrier_type_code: "cultivation_plate" })).toBe(
      false,
    );
    expect(LEGACY_GENERIC_CARRIER_TYPE_CODE).toBe("cultivation_plate");
  });

  it("includes the two distinct, non-legacy cultivation-plate types", () => {
    expect(
      isSelectableForCarrierRegistration({ status: "active", carrier_type_code: "nursery_cultivation_plate" }),
    ).toBe(true);
    expect(
      isSelectableForCarrierRegistration({ status: "active", carrier_type_code: "production_cultivation_plate" }),
    ).toBe(true);
  });

  it("includes seed_tray and other non-legacy types", () => {
    expect(isSelectableForCarrierRegistration({ status: "active", carrier_type_code: "seed_tray" })).toBe(true);
    expect(isSelectableForCarrierRegistration({ status: "active", carrier_type_code: "grow_cube" })).toBe(true);
  });

  it("excludes an inactive specification regardless of type", () => {
    expect(
      isSelectableForCarrierRegistration({ status: "inactive", carrier_type_code: "nursery_cultivation_plate" }),
    ).toBe(false);
  });
});

describe("generateCarrierCodePreview", () => {
  it("is deterministic for the same inputs", () => {
    expect(generateCarrierCodePreview("STR", 1, 5, 4)).toEqual(generateCarrierCodePreview("STR", 1, 5, 4));
  });

  it("produces explicit, unique, zero-padded codes", () => {
    const codes = generateCarrierCodePreview("STR", 1, 3, 4);
    expect(codes).toEqual(["STR0001", "STR0002", "STR0003"]);
    expect(new Set(codes).size).toBe(codes.length);
  });

  it("returns no preview for an invalid range or blank prefix", () => {
    expect(generateCarrierCodePreview("STR", 5, 1, 4)).toEqual([]);
    expect(generateCarrierCodePreview("", 1, 5, 4)).toEqual([]);
  });
});

describe("carrierRegistrationFormSchema", () => {
  it("requires a specification and a code in single mode", () => {
    const result = carrierRegistrationFormSchema.safeParse({
      ...DEFAULT_CARRIER_REGISTRATION_FORM_VALUES,
      specification_id: "",
      code: "",
    });
    expect(result.success).toBe(false);
  });

  it("accepts a valid single-mode submission", () => {
    const result = carrierRegistrationFormSchema.safeParse({
      ...DEFAULT_CARRIER_REGISTRATION_FORM_VALUES,
      specification_id: "spec-1",
      code: "STR-0001",
    });
    expect(result.success).toBe(true);
  });

  it("blocks an invalid range in bulk mode", () => {
    const result = carrierRegistrationFormSchema.safeParse({
      ...DEFAULT_CARRIER_REGISTRATION_FORM_VALUES,
      mode: "bulk",
      specification_id: "spec-1",
      code_prefix: "STR",
      start: 10,
      end: 1,
      pad_width: 4,
    });
    expect(result.success).toBe(false);
  });

  it("blocks a range exceeding the backend's MAX_BULK_CARRIERS limit", () => {
    const result = carrierRegistrationFormSchema.safeParse({
      ...DEFAULT_CARRIER_REGISTRATION_FORM_VALUES,
      mode: "bulk",
      specification_id: "spec-1",
      code_prefix: "STR",
      start: 1,
      end: MAX_BULK_CARRIERS + 1,
      pad_width: 4,
    });
    expect(result.success).toBe(false);
  });

  it("accepts a valid bulk-mode submission", () => {
    const result = carrierRegistrationFormSchema.safeParse({
      ...DEFAULT_CARRIER_REGISTRATION_FORM_VALUES,
      mode: "bulk",
      specification_id: "spec-1",
      code_prefix: "STR",
      start: 1,
      end: 100,
      pad_width: 4,
    });
    expect(result.success).toBe(true);
  });
});

describe("buildCarrierCreatePayload", () => {
  it("never includes carrier_type_code, location, batch, or plant-count fields", () => {
    const payload = buildCarrierCreatePayload({
      ...DEFAULT_CARRIER_REGISTRATION_FORM_VALUES,
      specification_id: "spec-1",
      code: " str-0001 ",
    });
    expect(payload).toEqual({ specification_id: "spec-1", code: "str-0001", issued_date: null });
    expect(payload).not.toHaveProperty("carrier_type_code");
  });
});

describe("buildCarrierBulkCreatePayload", () => {
  it("builds the exact backend-supported range/generator shape", () => {
    const payload = buildCarrierBulkCreatePayload({
      ...DEFAULT_CARRIER_REGISTRATION_FORM_VALUES,
      mode: "bulk",
      specification_id: "spec-1",
      code_prefix: "str",
      start: 1,
      end: 50,
      pad_width: 4,
    });
    expect(payload).toEqual({ specification_id: "spec-1", code_prefix: "str", start: 1, end: 50, pad_width: 4 });
  });
});
