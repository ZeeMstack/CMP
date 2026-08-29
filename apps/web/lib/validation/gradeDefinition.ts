import { z } from "zod";

import type { GradeDefinitionCreate, GradeDefinitionVersionCreate } from "@/lib/api/client";

/** PILOT-SETUP-001B7: exact `GradeDefinitionCreate` fields. `crop_id` is
 * required and `variety_id` is optional (NULL = "applies to all varieties
 * of that crop") -- mirrors `WorkflowForm`'s own Crop/Variety cascading
 * pattern exactly, including clearing Variety whenever Crop changes so a
 * mismatched pair can never be submitted. No quantity, grader, harvest lot,
 * or sample-result field belongs here -- those are operational Grading
 * concepts, never Grade Definition master data. */
export const gradeDefinitionFormSchema = z.object({
  crop_id: z.string().min(1, "Select a crop"),
  variety_id: z.string().nullable(),
  code: z.string().min(1, "Code is required"),
  name: z.string().min(1, "Name is required"),
  description: z.string().nullable(),
});
export type GradeDefinitionFormValues = z.infer<typeof gradeDefinitionFormSchema>;

export const DEFAULT_GRADE_DEFINITION_FORM_VALUES: GradeDefinitionFormValues = {
  crop_id: "",
  variety_id: null,
  code: "",
  name: "",
  description: null,
};

export function buildGradeDefinitionCreatePayload(
  values: GradeDefinitionFormValues,
  clientCommandId: string,
): GradeDefinitionCreate {
  return {
    client_command_id: clientCommandId,
    crop_id: values.crop_id,
    variety_id: values.variety_id || null,
    code: values.code.trim(),
    name: values.name.trim(),
    description: values.description?.trim() || null,
  };
}

/** Exact `GradeDefinitionVersionCreate` fields -- `spec_notes` only. Status
 * is never a form field: every draft version is created in `draft` state by
 * the backend itself, and activation is always a separate, explicit
 * follow-on command (see `versionLifecycleAction.ts`), never a flag on
 * this form. */
export const gradeDefinitionVersionFormSchema = z.object({
  spec_notes: z.string().nullable(),
});
export type GradeDefinitionVersionFormValues = z.infer<typeof gradeDefinitionVersionFormSchema>;

export const DEFAULT_GRADE_DEFINITION_VERSION_FORM_VALUES: GradeDefinitionVersionFormValues = {
  spec_notes: null,
};

export function buildGradeDefinitionVersionCreatePayload(
  values: GradeDefinitionVersionFormValues,
  clientCommandId: string,
): GradeDefinitionVersionCreate {
  return {
    client_command_id: clientCommandId,
    spec_notes: values.spec_notes?.trim() || null,
  };
}
