import { z } from "zod";

import type { InventoryItemCreate, InventoryItemUpdate } from "@/lib/api/client";

/** docs/domain/STORE_INVENTORY_MODEL.md §5: expiry tracking and QC release
 * are both InventoryLot-level concepts and meaningless on non-lot-tracked
 * material -- the UI must never let an operator submit an invalid
 * combination and rely only on the backend's 422. */
function refineTrackingPolicy<
  T extends { lotTrackingRequired: boolean; expiryTrackingRequired: boolean; qcReleaseRequired: boolean },
>(values: T, ctx: z.RefinementCtx) {
  if (values.expiryTrackingRequired && !values.lotTrackingRequired) {
    ctx.addIssue({
      code: z.ZodIssueCode.custom,
      path: ["lotTrackingRequired"],
      message: "Expiry tracking requires lot tracking",
    });
  }
  if (values.qcReleaseRequired && !values.lotTrackingRequired) {
    ctx.addIssue({
      code: z.ZodIssueCode.custom,
      path: ["lotTrackingRequired"],
      message: "QC release requires lot tracking",
    });
  }
}

export const inventoryItemFormSchema = z
  .object({
    code: z.string().min(1, "Code is required"),
    name: z.string().min(1, "Name is required"),
    categoryId: z.string().min(1, "Category is required"),
    baseUomId: z.string().min(1, "Base unit of measure is required"),
    lotTrackingRequired: z.boolean(),
    expiryTrackingRequired: z.boolean(),
    qcReleaseRequired: z.boolean(),
  })
  .superRefine(refineTrackingPolicy);
export type InventoryItemFormValues = z.infer<typeof inventoryItemFormSchema>;

export const DEFAULT_INVENTORY_ITEM_FORM_VALUES: InventoryItemFormValues = {
  code: "",
  name: "",
  categoryId: "",
  baseUomId: "",
  lotTrackingRequired: false,
  expiryTrackingRequired: false,
  qcReleaseRequired: false,
};

export function buildInventoryItemCreatePayload(
  values: InventoryItemFormValues,
  clientCommandId: string,
): InventoryItemCreate {
  return {
    client_command_id: clientCommandId,
    code: values.code.trim(),
    name: values.name.trim(),
    category_id: values.categoryId,
    base_uom_id: values.baseUomId,
    lot_tracking_required: values.lotTrackingRequired,
    expiry_tracking_required: values.expiryTrackingRequired,
    qc_release_required: values.qcReleaseRequired,
  };
}

export const inventoryItemUpdateFormSchema = z
  .object({
    name: z.string().min(1, "Name is required"),
    categoryId: z.string().min(1, "Category is required"),
    baseUomId: z.string().min(1, "Base unit of measure is required"),
    lotTrackingRequired: z.boolean(),
    expiryTrackingRequired: z.boolean(),
    qcReleaseRequired: z.boolean(),
  })
  .superRefine(refineTrackingPolicy);
export type InventoryItemUpdateFormValues = z.infer<typeof inventoryItemUpdateFormSchema>;

export function buildInventoryItemUpdatePayload(
  values: InventoryItemUpdateFormValues,
  clientCommandId: string,
): InventoryItemUpdate {
  return {
    client_command_id: clientCommandId,
    name: values.name.trim(),
    category_id: values.categoryId,
    base_uom_id: values.baseUomId,
    lot_tracking_required: values.lotTrackingRequired,
    expiry_tracking_required: values.expiryTrackingRequired,
    qc_release_required: values.qcReleaseRequired,
  };
}
