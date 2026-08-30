import { z } from "zod";

import type { ProductionSystemCreate } from "@/lib/api/client";

/** PILOT-SETUP-001B6: exact backend fields only (`code`, `name`,
 * `description`) -- no fertigation recipe, climate setting, or hardware
 * configuration field exists on `ProductionSystemCreate`. */
export const productionSystemFormSchema = z.object({
  code: z.string().min(1, "Code is required"),
  name: z.string().min(1, "Name is required"),
  description: z.string().nullable(),
});
export type ProductionSystemFormValues = z.infer<typeof productionSystemFormSchema>;

export const DEFAULT_PRODUCTION_SYSTEM_FORM_VALUES: ProductionSystemFormValues = {
  code: "",
  name: "",
  description: null,
};

export function buildProductionSystemCreatePayload(
  values: ProductionSystemFormValues,
): ProductionSystemCreate {
  return {
    code: values.code.trim(),
    name: values.name.trim(),
    description: values.description?.trim() || null,
  };
}
