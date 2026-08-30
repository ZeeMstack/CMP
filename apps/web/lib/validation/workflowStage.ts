import { z } from "zod";

import type { WorkflowStageCreate } from "@/lib/api/client";

/** PILOT-SETUP-001B6: mirrors `app.models.workflow_stage.STAGE_CATEGORIES`
 * exactly -- human-friendly labels only, the enum values sent to the
 * backend never change. Never invents a category the backend doesn't have. */
export const STAGE_CATEGORY_OPTIONS = [
  { value: "seeding", label: "Seeding" },
  { value: "germination", label: "Germination" },
  { value: "nursery", label: "Nursery" },
  { value: "transplanting", label: "Transplanting" },
  { value: "intermediate", label: "Intermediate" },
  { value: "production", label: "Production" },
  { value: "harvest_ready", label: "Harvest ready" },
  { value: "harvesting", label: "Harvesting" },
  { value: "completed", label: "Completed" },
  { value: "rejected", label: "Rejected" },
] as const;

const STAGE_CATEGORY_VALUES = STAGE_CATEGORY_OPTIONS.map((o) => o.value) as [string, ...string[]];

/** `permitted_location_type_code` is deliberately not a field on this form:
 * `LocationType` (unlike `CarrierType`) has no list endpoint on the backend
 * today, so there is no safe way to offer a dropdown of valid codes without
 * guessing at values that may not exist -- see the B6 report. The stage is
 * always created with `permitted_location_type_id: null` (an already-
 * supported, unconstrained state), never a fabricated code. */
export const workflowStageFormSchema = z.object({
  code: z.string().min(1, "Code is required"),
  name: z.string().min(1, "Name is required"),
  display_order: z.number().int("Must be a whole number").min(0, "Must be zero or greater"),
  stage_category: z.enum(STAGE_CATEGORY_VALUES, { message: "Select a stage category" }),
  expected_duration_minutes: z.number().int("Must be a whole number").positive("Must be greater than zero").nullable(),
  required_carrier_type_code: z.string().nullable(),
  is_start: z.boolean(),
  is_terminal: z.boolean(),
});
export type WorkflowStageFormValues = z.infer<typeof workflowStageFormSchema>;

export function defaultWorkflowStageFormValues(nextDisplayOrder: number): WorkflowStageFormValues {
  return {
    code: "",
    name: "",
    display_order: nextDisplayOrder,
    stage_category: "seeding",
    expected_duration_minutes: null,
    required_carrier_type_code: null,
    is_start: false,
    is_terminal: false,
  };
}

export function buildWorkflowStageCreatePayload(values: WorkflowStageFormValues): WorkflowStageCreate {
  return {
    code: values.code.trim(),
    name: values.name.trim(),
    display_order: values.display_order,
    stage_category: values.stage_category,
    expected_duration_minutes: values.expected_duration_minutes,
    permitted_location_type_code: null,
    required_carrier_type_code: values.required_carrier_type_code || null,
    is_start: values.is_start,
    is_terminal: values.is_terminal,
  };
}
