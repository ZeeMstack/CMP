import { z } from "zod";

import type { PackSpecificationCreate, PackSpecificationVersionCreate } from "@/lib/api/client";

/** PILOT-SETUP-001B7: exact `PackSpecificationCreate` fields. `crop_id` is
 * required and `variety_id` is optional, mirroring `gradeDefinition.ts`'s
 * own scope exactly. `customer_reference` is deliberately free text (no
 * Customer/SalesOrder entity exists) -- never price, delivery route, or
 * inventory quantity. */
export const packSpecificationFormSchema = z.object({
  crop_id: z.string().min(1, "Select a crop"),
  variety_id: z.string().nullable(),
  code: z.string().min(1, "Code is required"),
  name: z.string().min(1, "Name is required"),
  customer_reference: z.string().nullable(),
});
export type PackSpecificationFormValues = z.infer<typeof packSpecificationFormSchema>;

export const DEFAULT_PACK_SPECIFICATION_FORM_VALUES: PackSpecificationFormValues = {
  crop_id: "",
  variety_id: null,
  code: "",
  name: "",
  customer_reference: null,
};

export function buildPackSpecificationCreatePayload(
  values: PackSpecificationFormValues,
  clientCommandId: string,
): PackSpecificationCreate {
  return {
    client_command_id: clientCommandId,
    crop_id: values.crop_id,
    variety_id: values.variety_id || null,
    code: values.code.trim(),
    name: values.name.trim(),
    customer_reference: values.customer_reference?.trim() || null,
  };
}

/** Exact `PackSpecificationVersionCreate` fields. `grade_definition_version_id`
 * is genuinely optional on the backend -- not every Pack Specification ties
 * to a Grade. The frozen pack-measure rule (`nominal_net_weight_kg IS NOT
 * NULL OR whole_units_per_pack IS NOT NULL`) is mirrored exactly via
 * `.refine`, not invented stricter (neither field is required on its own,
 * and both may be present together). */
export const packSpecificationVersionFormSchema = z
  .object({
    grade_definition_version_id: z.string().nullable(),
    packaging_unit_id: z.string().min(1, "Select a packaging unit"),
    nominal_net_weight_kg: z.number().positive("Must be greater than 0").nullable(),
    whole_units_per_pack: z.number().int().positive("Must be greater than 0").nullable(),
    spec_notes: z.string().nullable(),
  })
  .refine((v) => v.nominal_net_weight_kg != null || v.whole_units_per_pack != null, {
    message: "Enter a nominal net weight, whole units per pack, or both",
    path: ["nominal_net_weight_kg"],
  });
export type PackSpecificationVersionFormValues = z.infer<typeof packSpecificationVersionFormSchema>;

export const DEFAULT_PACK_SPECIFICATION_VERSION_FORM_VALUES: PackSpecificationVersionFormValues = {
  grade_definition_version_id: null,
  packaging_unit_id: "",
  nominal_net_weight_kg: null,
  whole_units_per_pack: null,
  spec_notes: null,
};

export function buildPackSpecificationVersionCreatePayload(
  values: PackSpecificationVersionFormValues,
  clientCommandId: string,
): PackSpecificationVersionCreate {
  return {
    client_command_id: clientCommandId,
    grade_definition_version_id: values.grade_definition_version_id || null,
    packaging_unit_id: values.packaging_unit_id,
    nominal_net_weight_kg: values.nominal_net_weight_kg,
    whole_units_per_pack: values.whole_units_per_pack,
    spec_notes: values.spec_notes?.trim() || null,
  };
}
