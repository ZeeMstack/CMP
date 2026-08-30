import { describe, expect, it } from "vitest";

import {
  DEFAULT_LOCATION_FORM_VALUES,
  MAX_BULK_LOCATION_CHILDREN,
  buildLocationBulkChildrenPayload,
  buildLocationCreatePayload,
  generateLocationCodePreview,
  locationFormSchema,
} from "./location";

describe("generateLocationCodePreview", () => {
  it("is deterministic for the same inputs", () => {
    const a = generateLocationCodePreview("CS", 1, 5, 2);
    const b = generateLocationCodePreview("CS", 1, 5, 2);
    expect(a).toEqual(b);
  });

  it("produces explicit, unique, zero-padded codes matching the backend's own generator", () => {
    expect(generateLocationCodePreview("CS", 1, 3, 2)).toEqual(["CS01", "CS02", "CS03"]);
    const codes = generateLocationCodePreview("CS", 8, 12, 3);
    expect(codes).toEqual(["CS008", "CS009", "CS010", "CS011", "CS012"]);
    expect(new Set(codes).size).toBe(codes.length);
  });

  it("uppercases the prefix, mirroring the backend's own normalization", () => {
    expect(generateLocationCodePreview("cs", 1, 1, 2)).toEqual(["CS01"]);
  });

  it("returns no preview for an invalid range or blank prefix", () => {
    expect(generateLocationCodePreview("CS", 5, 1, 2)).toEqual([]);
    expect(generateLocationCodePreview("", 1, 5, 2)).toEqual([]);
  });
});

describe("locationFormSchema", () => {
  it("requires code and name in single mode", () => {
    const result = locationFormSchema.safeParse({
      ...DEFAULT_LOCATION_FORM_VALUES,
      mode: "single",
      location_type_code: "packing_hall",
      code: "",
      name: "",
    });
    expect(result.success).toBe(false);
  });

  it("accepts a valid single-mode submission", () => {
    const result = locationFormSchema.safeParse({
      ...DEFAULT_LOCATION_FORM_VALUES,
      mode: "single",
      location_type_code: "packing_hall",
      code: "PH1",
      name: "Packing Hall 1",
    });
    expect(result.success).toBe(true);
  });

  it("requires a parent location in bulk mode (bulk-children has no root-level form)", () => {
    const result = locationFormSchema.safeParse({
      ...DEFAULT_LOCATION_FORM_VALUES,
      mode: "bulk",
      location_type_code: "cold_store_position",
      parent_location_id: "",
      code_prefix: "P",
      start: 1,
      end: 5,
      pad_width: 2,
    });
    expect(result.success).toBe(false);
  });

  it("blocks an invalid range (end before start)", () => {
    const result = locationFormSchema.safeParse({
      ...DEFAULT_LOCATION_FORM_VALUES,
      mode: "bulk",
      location_type_code: "cold_store_position",
      parent_location_id: "cold-store-1",
      code_prefix: "P",
      start: 5,
      end: 1,
      pad_width: 2,
    });
    expect(result.success).toBe(false);
  });

  it("blocks a range exceeding the backend's MAX_BULK_CHILDREN limit", () => {
    const result = locationFormSchema.safeParse({
      ...DEFAULT_LOCATION_FORM_VALUES,
      mode: "bulk",
      location_type_code: "cold_store_position",
      parent_location_id: "cold-store-1",
      code_prefix: "P",
      start: 1,
      end: MAX_BULK_LOCATION_CHILDREN + 1,
      pad_width: 3,
    });
    expect(result.success).toBe(false);
  });

  it("accepts a valid bulk-mode submission", () => {
    const result = locationFormSchema.safeParse({
      ...DEFAULT_LOCATION_FORM_VALUES,
      mode: "bulk",
      location_type_code: "cold_store_position",
      parent_location_id: "cold-store-1",
      code_prefix: "P",
      start: 1,
      end: 10,
      pad_width: 2,
    });
    expect(result.success).toBe(true);
  });
});

describe("buildLocationCreatePayload", () => {
  it("maps an empty parent selection to null, never an empty string", () => {
    const payload = buildLocationCreatePayload({
      ...DEFAULT_LOCATION_FORM_VALUES,
      location_type_code: "packing_hall",
      code: " ph1 ",
      name: " Packing Hall 1 ",
      parent_location_id: "",
    });
    expect(payload).toEqual({
      location_type_code: "packing_hall",
      code: "ph1",
      name: "Packing Hall 1",
      parent_location_id: null,
      capacity: null,
    });
  });
});

describe("buildLocationBulkChildrenPayload", () => {
  it("builds the exact backend-supported range/generator shape", () => {
    const payload = buildLocationBulkChildrenPayload({
      ...DEFAULT_LOCATION_FORM_VALUES,
      location_type_code: "cold_store_position",
      code_prefix: "p",
      start: 1,
      end: 20,
      pad_width: 3,
      capacity: 1,
    });
    expect(payload).toEqual({
      location_type_code: "cold_store_position",
      code_prefix: "p",
      start: 1,
      end: 20,
      pad_width: 3,
      name_template: null,
      capacity: 1,
    });
  });
});
