import { z } from "zod";

import type { InventoryCategoryCreate, InventoryCategoryUpdate } from "@/lib/api/client";

export const inventoryCategoryFormSchema = z.object({
  code: z.string().min(1, "Code is required"),
  name: z.string().min(1, "Name is required"),
});
export type InventoryCategoryFormValues = z.infer<typeof inventoryCategoryFormSchema>;

export const DEFAULT_INVENTORY_CATEGORY_FORM_VALUES: InventoryCategoryFormValues = {
  code: "",
  name: "",
};

export function buildInventoryCategoryCreatePayload(
  values: InventoryCategoryFormValues,
  clientCommandId: string,
): InventoryCategoryCreate {
  return {
    client_command_id: clientCommandId,
    code: values.code.trim(),
    name: values.name.trim(),
  };
}

export const inventoryCategoryUpdateFormSchema = z.object({
  name: z.string().min(1, "Name is required"),
});
export type InventoryCategoryUpdateFormValues = z.infer<typeof inventoryCategoryUpdateFormSchema>;

export function buildInventoryCategoryUpdatePayload(
  values: InventoryCategoryUpdateFormValues,
  clientCommandId: string,
): InventoryCategoryUpdate {
  return {
    client_command_id: clientCommandId,
    name: values.name.trim(),
  };
}
