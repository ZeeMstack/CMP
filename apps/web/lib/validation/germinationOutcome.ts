import { z } from "zod";

import type { GerminationOutcomeCommandCreate } from "@/lib/api/client";

/** NURSERY-OPS-002B: the modern, INDIVIDUAL-SEEDLING-based Germination
 * outcome -- distinct from the legacy site-based GerminationCheck. Both
 * `normal_seedling_count` and `abnormal_seedling_count` are LIVING counts;
 * abnormal is never treated as a loss here. The Tray itself is chosen
 * outside this schema (in the page/form component, from the farm-wide
 * Germination Trays list) -- this schema only covers the outcome entry
 * fields for one already-selected Tray. */

export const germinationOutcomeFormSchema = z.object({
  normal_seedling_count: z
    .number({ error: "Normal seedlings is required" })
    .int("Must be a whole number")
    .min(0, "Must be zero or more"),
  abnormal_seedling_count: z
    .number({ error: "Abnormal seedlings is required" })
    .int("Must be a whole number")
    .min(0, "Must be zero or more"),
  assessment_complete: z.boolean(),
  effective_date: z.string().min(1, "Date is required"),
  effective_time_of_day: z.string().min(1, "Time is required"),
  note: z.string(),
});
export type GerminationOutcomeFormValues = z.infer<typeof germinationOutcomeFormSchema>;

export const DEFAULT_GERMINATION_OUTCOME_FORM_VALUES: GerminationOutcomeFormValues = {
  normal_seedling_count: 0,
  abnormal_seedling_count: 0,
  assessment_complete: false,
  effective_date: "",
  effective_time_of_day: "",
  note: "",
};

export function buildGerminationOutcomePayload(
  values: GerminationOutcomeFormValues,
  clientCommandId: string,
  batchCarrierAssignmentId: string,
): GerminationOutcomeCommandCreate {
  return {
    client_command_id: clientCommandId,
    effective_time: new Date(`${values.effective_date}T${values.effective_time_of_day}`).toISOString(),
    note: null,
    outcomes: [
      {
        batch_carrier_assignment_id: batchCarrierAssignmentId,
        normal_seedling_count: values.normal_seedling_count,
        abnormal_seedling_count: values.abnormal_seedling_count,
        assessment_complete: values.assessment_complete,
        note: values.note.trim() || null,
      },
    ],
  };
}

export function livingSeedlingCount(values: { normal_seedling_count: number; abnormal_seedling_count: number }): number {
  const normal = Number.isFinite(values.normal_seedling_count) ? values.normal_seedling_count : 0;
  const abnormal = Number.isFinite(values.abnormal_seedling_count) ? values.abnormal_seedling_count : 0;
  return normal + abnormal;
}
