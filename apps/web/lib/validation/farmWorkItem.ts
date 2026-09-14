import { z } from "zod";

import type { FarmWorkItemCreate } from "@/lib/api/client";

/** PILOT-OPS-001: the manual Work Item creation form. Scoped to the
 * ticket's own "Manual Work Items" examples (cleaning/inspection/
 * preparation) -- location/asset/carrier/batch context pickers do not
 * exist yet for this form (see docs/product/OPEN_QUESTIONS.md); creating
 * an OPERATIONAL_RECORD Work Item with real batch/context is currently a
 * backend-only capability (proven by the Harvest/Observation integration
 * tests), not yet exposed through this compact manual form. */
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
    completion_mode: "manual_record",
  };
}
