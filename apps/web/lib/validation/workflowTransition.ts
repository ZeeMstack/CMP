import { z } from "zod";

import type { WorkflowTransitionCreate } from "@/lib/api/client";

/** PILOT-SETUP-001B6: `from_stage_id !== to_stage_id` mirrors the backend's
 * own `SelfTransitionError` (a stage cannot transition to itself) -- caught
 * client-side before the request is even sent, and still enforced
 * server-side regardless. This is a physical-workflow permission graph
 * only; it never implies a biological Movement. */
export const workflowTransitionFormSchema = z
  .object({
    from_stage_id: z.string().min(1, "Select a from-stage"),
    to_stage_id: z.string().min(1, "Select a to-stage"),
    code: z.string().min(1, "Code is required"),
    name: z.string().min(1, "Name is required"),
  })
  .refine((v) => v.from_stage_id !== v.to_stage_id, {
    message: "A stage cannot transition to itself",
    path: ["to_stage_id"],
  });
export type WorkflowTransitionFormValues = z.infer<typeof workflowTransitionFormSchema>;

export const DEFAULT_WORKFLOW_TRANSITION_FORM_VALUES: WorkflowTransitionFormValues = {
  from_stage_id: "",
  to_stage_id: "",
  code: "",
  name: "",
};

export function buildWorkflowTransitionCreatePayload(
  values: WorkflowTransitionFormValues,
): WorkflowTransitionCreate {
  return {
    from_stage_id: values.from_stage_id,
    to_stage_id: values.to_stage_id,
    code: values.code.trim(),
    name: values.name.trim(),
  };
}
