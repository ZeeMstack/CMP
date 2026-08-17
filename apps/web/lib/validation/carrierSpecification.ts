import { z } from "zod";

import type { CarrierSpecificationCreate, CarrierSpecificationUpdate } from "@/lib/api/client";

/** CARRIER-CONFIG-001: dimensions are canonical whole millimeters (never a
 * unit picker, never a float -- matches the backend's own
 * `length_mm`/`width_mm`/`height_mm`/`biological_position_count` columns).
 * `carrier_type_code` is fixed once a specification exists anywhere on the
 * form: the create/edit form always resolves it from the already-selected
 * Carrier Type, never free text. */

const optionalPositiveInt = z
  .number()
  .int("Must be a whole number")
  .positive("Must be greater than zero")
  .nullable();

export const carrierSpecificationFormSchema = z.object({
  carrier_type_code: z.string().min(1, "Carrier type is required"),
  code: z.string().min(1, "Code is required"),
  name: z.string().min(1, "Name is required"),
  length_mm: optionalPositiveInt,
  width_mm: optionalPositiveInt,
  height_mm: optionalPositiveInt,
  biological_position_count: optionalPositiveInt,
});
export type CarrierSpecificationFormValues = z.infer<typeof carrierSpecificationFormSchema>;

export const DEFAULT_CARRIER_SPECIFICATION_FORM_VALUES: CarrierSpecificationFormValues = {
  carrier_type_code: "",
  code: "",
  name: "",
  length_mm: null,
  width_mm: null,
  height_mm: null,
  biological_position_count: null,
};

export function buildCarrierSpecificationCreatePayload(
  values: CarrierSpecificationFormValues,
): CarrierSpecificationCreate {
  return {
    carrier_type_code: values.carrier_type_code,
    code: values.code.trim(),
    name: values.name.trim(),
    length_mm: values.length_mm,
    width_mm: values.width_mm,
    height_mm: values.height_mm,
    biological_position_count: values.biological_position_count,
  };
}

export function buildCarrierSpecificationUpdatePayload(
  values: CarrierSpecificationFormValues,
): CarrierSpecificationUpdate {
  return buildCarrierSpecificationCreatePayload(values);
}
