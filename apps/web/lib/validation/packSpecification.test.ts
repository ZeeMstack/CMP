import { describe, expect, it } from "vitest";

import {
  DEFAULT_PACK_SPECIFICATION_VERSION_FORM_VALUES,
  buildPackSpecificationCreatePayload,
  buildPackSpecificationVersionCreatePayload,
  packSpecificationVersionFormSchema,
} from "./packSpecification";

/** PILOT-SETUP-001B7: mirrors the backend's own frozen pack-measure rule
 * (`ck_pack_specification_versions_measure_present`) exactly -- at least one
 * of nominal weight or whole units per pack, never both required. */
describe("packSpecificationVersionFormSchema", () => {
  const base = {
    ...DEFAULT_PACK_SPECIFICATION_VERSION_FORM_VALUES,
    packaging_unit_id: "unit-1",
  };

  it("rejects neither measure present", () => {
    const result = packSpecificationVersionFormSchema.safeParse(base);
    expect(result.success).toBe(false);
  });

  it("accepts nominal weight only", () => {
    const result = packSpecificationVersionFormSchema.safeParse({ ...base, nominal_net_weight_kg: 5 });
    expect(result.success).toBe(true);
  });

  it("accepts whole units per pack only", () => {
    const result = packSpecificationVersionFormSchema.safeParse({ ...base, whole_units_per_pack: 12 });
    expect(result.success).toBe(true);
  });

  it("accepts both measures together", () => {
    const result = packSpecificationVersionFormSchema.safeParse({
      ...base,
      nominal_net_weight_kg: 5,
      whole_units_per_pack: 12,
    });
    expect(result.success).toBe(true);
  });

  it("requires a packaging unit regardless of measures", () => {
    const result = packSpecificationVersionFormSchema.safeParse({ ...base, packaging_unit_id: "", nominal_net_weight_kg: 5 });
    expect(result.success).toBe(false);
  });
});

describe("buildPackSpecificationCreatePayload", () => {
  it("builds exact PackSpecificationCreate fields, trimming text and nulling blanks", () => {
    const payload = buildPackSpecificationCreatePayload(
      { crop_id: "crop-1", variety_id: null, code: " ICE-5KG ", name: " Iceberg 5kg ", customer_reference: "  " },
      "cmd-1",
    );
    expect(payload).toEqual({
      client_command_id: "cmd-1",
      crop_id: "crop-1",
      variety_id: null,
      code: "ICE-5KG",
      name: "Iceberg 5kg",
      customer_reference: null,
    });
  });
});

describe("buildPackSpecificationVersionCreatePayload", () => {
  it("sends null (never 0) for an untouched optional measure", () => {
    const payload = buildPackSpecificationVersionCreatePayload(
      { ...DEFAULT_PACK_SPECIFICATION_VERSION_FORM_VALUES, packaging_unit_id: "unit-1", whole_units_per_pack: 12 },
      "cmd-1",
    );
    expect(payload.nominal_net_weight_kg).toBeNull();
    expect(payload.whole_units_per_pack).toBe(12);
  });
});
