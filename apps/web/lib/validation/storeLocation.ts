import { z } from "zod";

import type { LocationBulkChildrenCreate, LocationCreate } from "@/lib/api/client";

/** docs/domain/STORE_INVENTORY_MODEL.md §4/§9: a purpose-built, constrained
 * counterpart to the fully generic `LocationCreateForm` -- the operator
 * never sees a free-text location-type picker or an unfiltered parent list
 * here; each mode below hardcodes the one legal `location_type_code` for
 * that action, and the page only ever offers parents of a type that mode
 * actually permits. `occupiable`/`greenhouse_classification` are never
 * sent -- every Store-tree type's system default is already correct
 * (`store`/`store_area`/`store_rack` non-occupiable, `store_bin`
 * occupiable). */

export const MAX_BULK_BINS = 500;

function normalizeCode(v: string): string {
  return v.trim().toUpperCase();
}

export const newStoreFormSchema = z.object({
  code: z.string().min(1, "Code is required"),
  name: z.string().min(1, "Name is required"),
});
export type NewStoreFormValues = z.infer<typeof newStoreFormSchema>;

export function buildNewStorePayload(values: NewStoreFormValues): LocationCreate {
  return {
    location_type_code: "store",
    code: normalizeCode(values.code),
    name: values.name.trim(),
    parent_location_id: null,
    greenhouse_classification: null,
    occupiable: null,
  };
}

export const addAreaFormSchema = z.object({
  parentLocationId: z.string().min(1, "Store is required"),
  code: z.string().min(1, "Code is required"),
  name: z.string().min(1, "Name is required"),
});
export type AddAreaFormValues = z.infer<typeof addAreaFormSchema>;

export function buildAddAreaPayload(values: AddAreaFormValues): LocationCreate {
  return {
    location_type_code: "store_area",
    code: normalizeCode(values.code),
    name: values.name.trim(),
    parent_location_id: values.parentLocationId,
    greenhouse_classification: null,
    occupiable: null,
  };
}

export const addRackFormSchema = z.object({
  parentLocationId: z.string().min(1, "Parent is required"),
  code: z.string().min(1, "Code is required"),
  name: z.string().min(1, "Name is required"),
});
export type AddRackFormValues = z.infer<typeof addRackFormSchema>;

export function buildAddRackPayload(values: AddRackFormValues): LocationCreate {
  return {
    location_type_code: "store_rack",
    code: normalizeCode(values.code),
    name: values.name.trim(),
    parent_location_id: values.parentLocationId,
    greenhouse_classification: null,
    occupiable: null,
  };
}

export const addBinFormSchema = z
  .object({
    parentLocationId: z.string().min(1, "Parent is required"),
    mode: z.enum(["single", "bulk"]),
    code: z.string(),
    name: z.string(),
    codePrefix: z.string(),
    start: z.number().int().positive(),
    end: z.number().int().positive(),
    padWidth: z.number().int().positive(),
    nameTemplate: z.string(),
  })
  .superRefine((values, ctx) => {
    if (values.mode === "single") {
      if (!values.code.trim()) {
        ctx.addIssue({ code: z.ZodIssueCode.custom, path: ["code"], message: "Code is required" });
      }
      if (!values.name.trim()) {
        ctx.addIssue({ code: z.ZodIssueCode.custom, path: ["name"], message: "Name is required" });
      }
      return;
    }
    if (!values.codePrefix.trim()) {
      ctx.addIssue({ code: z.ZodIssueCode.custom, path: ["codePrefix"], message: "Code prefix is required" });
    }
    if (values.end < values.start) {
      ctx.addIssue({ code: z.ZodIssueCode.custom, path: ["end"], message: "End must be ≥ start" });
    }
    if (values.end - values.start + 1 > MAX_BULK_BINS) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom, path: ["end"],
        message: `Cannot generate more than ${MAX_BULK_BINS} bins per command`,
      });
    }
  });
export type AddBinFormValues = z.infer<typeof addBinFormSchema>;

export const DEFAULT_ADD_BIN_FORM_VALUES: AddBinFormValues = {
  parentLocationId: "",
  mode: "single",
  code: "",
  name: "",
  codePrefix: "BIN-",
  start: 1,
  end: 10,
  padWidth: 3,
  nameTemplate: "",
};

export function buildAddBinSinglePayload(values: AddBinFormValues): LocationCreate {
  return {
    location_type_code: "store_bin",
    code: normalizeCode(values.code),
    name: values.name.trim(),
    parent_location_id: values.parentLocationId,
    greenhouse_classification: null,
    occupiable: null,
  };
}

export function buildAddBinBulkPayload(values: AddBinFormValues): LocationBulkChildrenCreate {
  return {
    location_type_code: "store_bin",
    code_prefix: values.codePrefix.trim().toUpperCase(),
    start: values.start,
    end: values.end,
    pad_width: values.padWidth,
    name_template: values.nameTemplate.trim() || null,
    capacity: null,
  };
}
