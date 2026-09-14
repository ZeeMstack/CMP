import { z } from "zod";

import type { FarmWorkItemCreate } from "@/lib/api/client";

/** PILOT-OPS-001: the manual Work Item creation form. Scoped to the
 * ticket's own "Manual Work Items" examples (cleaning/inspection/
 * preparation), plus optional structured Location/Batch/Asset/Carrier
 * context (PILOT-OPS-001 closure) -- reuses the same authoritative
 * entity ids PILOT-SCAN-001 will later resolve from a QR scan, never a
 * display-string-only field. Creating an OPERATIONAL_RECORD Work Item is
 * still backend-only (proven by the Harvest/Observation integration
 * tests) -- this form always creates MANUAL_RECORD items. */
export const workItemCategoryOptions = [
  "nursery", "production", "crop_care", "harvest", "post_harvest",
  "store", "quality", "dispatch", "cleaning", "maintenance",
] as const;

export const workItemPriorityOptions = ["normal", "high", "critical"] as const;

export const farmWorkItemFormSchema = z.object({
  workType: z.string().min(1, "Work type is required"),
  category: z.enum(workItemCategoryOptions),
  title: z.string().min(1, "Title is required"),
  instructions: z.string().nullable(),
  priority: z.enum(workItemPriorityOptions),
  dueAt: z.string().nullable(), // datetime-local string, or null
  assignToMe: z.boolean(),
  locationId: z.string().nullable(),
  cropBatchId: z.string().nullable(),
  assetId: z.string().nullable(),
  carrierId: z.string().nullable(),
});
export type FarmWorkItemFormValues = z.infer<typeof farmWorkItemFormSchema>;

export const DEFAULT_FARM_WORK_ITEM_FORM_VALUES: FarmWorkItemFormValues = {
  workType: "",
  category: "maintenance",
  title: "",
  instructions: null,
  priority: "normal",
  dueAt: null,
  assignToMe: false,
  locationId: null,
  cropBatchId: null,
  assetId: null,
  carrierId: null,
};

export function buildFarmWorkItemCreatePayload(
  values: FarmWorkItemFormValues,
  options: { clientCommandId: string; currentUserId?: string },
): FarmWorkItemCreate {
  return {
    client_command_id: options.clientCommandId,
    work_type: values.workType.trim(),
    category: values.category,
    title: values.title.trim(),
    instructions: values.instructions?.trim() || null,
    priority: values.priority,
    // A bare `datetime-local` value has no timezone -- CMP always sends
    // tz-aware instants (CLAUDE.md "Time"), so it is interpreted as the
    // operator's own browser-local wall-clock time, exactly like every
    // other `datetime-local` input in this app (see lib/datetime.ts).
    due_at: values.dueAt ? new Date(values.dueAt).toISOString() : null,
    assigned_to_user_id: values.assignToMe ? (options.currentUserId ?? null) : null,
    location_id: values.locationId || null,
    crop_batch_id: values.cropBatchId || null,
    asset_id: values.assetId || null,
    carrier_id: values.carrierId || null,
    completion_mode: "manual_record",
  };
}
