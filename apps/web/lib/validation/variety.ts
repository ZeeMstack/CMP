import { z } from "zod";

import type { VarietyCreate } from "@/lib/api/client";

/** PILOT-SETUP-001B6: `supplier_reference` is genuinely optional on the
 * backend (`VarietyCreate.supplier_reference: str | None = None`) -- never
 * required here. No seed lot/supplier account/quantity/germination-%/batch
 * field exists on this form; those are outside Variety master data. */
export const varietyFormSchema = z.object({
  code: z.string().min(1, "Code is required"),
  name: z.string().min(1, "Name is required"),
  supplier_reference: z.string().nullable(),
});
export type VarietyFormValues = z.infer<typeof varietyFormSchema>;

export const DEFAULT_VARIETY_FORM_VALUES: VarietyFormValues = {
  code: "",
  name: "",
  supplier_reference: null,
};

export function buildVarietyCreatePayload(values: VarietyFormValues): VarietyCreate {
  return {
    code: values.code.trim(),
    name: values.name.trim(),
    supplier_reference: values.supplier_reference?.trim() || null,
  };
}
