import { z } from "zod";

import type { WorkflowCreate } from "@/lib/api/client";

/** PILOT-SETUP-001B6: exact `WorkflowCreate` fields. `variety_id` is
 * genuinely optional on the backend and, when set, must belong to the
 * selected Crop (`VarietyCropMismatchError` if not) -- this form only ever
 * offers Varieties already scoped to the selected Crop, so that mismatch
 * cannot be constructed from the UI. */
export const workflowFormSchema = z.object({
  crop_id: z.string().min(1, "Select a crop"),
  variety_id: z.string().nullable(),
  production_system_id: z.string().min(1, "Select a production system"),
  code: z.string().min(1, "Code is required"),
  name: z.string().min(1, "Name is required"),
});
export type WorkflowFormValues = z.infer<typeof workflowFormSchema>;

export const DEFAULT_WORKFLOW_FORM_VALUES: WorkflowFormValues = {
  crop_id: "",
  variety_id: null,
  production_system_id: "",
  code: "",
  name: "",
};

export function buildWorkflowCreatePayload(values: WorkflowFormValues): WorkflowCreate {
  return {
    crop_id: values.crop_id,
    variety_id: values.variety_id || null,
    production_system_id: values.production_system_id,
    code: values.code.trim(),
    name: values.name.trim(),
  };
}
