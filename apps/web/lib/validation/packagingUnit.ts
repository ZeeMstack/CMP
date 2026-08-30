import { z } from "zod";

import type { PackagingUnitCreate } from "@/lib/api/client";

/** PILOT-SETUP-001B7: exact `PackagingUnitCreate` fields -- `code`/`name`
 * only. No pack-size measure (nominal weight, whole units per pack) belongs
 * here; those live on `PackSpecificationVersion`, never on the reusable
 * Packaging Unit identity itself. */
export const packagingUnitFormSchema = z.object({
  code: z.string().min(1, "Code is required"),
  name: z.string().min(1, "Name is required"),
});
export type PackagingUnitFormValues = z.infer<typeof packagingUnitFormSchema>;

export const DEFAULT_PACKAGING_UNIT_FORM_VALUES: PackagingUnitFormValues = {
  code: "",
  name: "",
};

export function buildPackagingUnitCreatePayload(
  values: PackagingUnitFormValues,
  clientCommandId: string,
): PackagingUnitCreate {
  return {
    client_command_id: clientCommandId,
    code: values.code.trim(),
    name: values.name.trim(),
  };
}
