import { z } from "zod";

/** POSTHARVEST-OPS-001G: Record Grading (one source Harvested Produce Lot,
 * one or more Graded Produce Lot outputs, full weight/count reconciliation).
 * Client-side validation is convenience only -- the server remains the sole
 * authority (mirrors `lib/validation/leafyHarvest.ts`'s own established
 * shape and comment). The balance check here (input presented = rejected +
 * loss + sample + remainder + sum(outputs)) is not confirmed to be
 * separately enforced server-side, but is exactly what the ticket's "live
 * reconciliation" requirement calls for, so it is enforced here regardless. */

const WEIGHT_EPSILON = 0.001;

export const gradingOutputFormSchema = z.object({
  grade_definition_version_id: z.string().min(1, "Select a grade"),
  grade_definition_label: z.string(),
  code: z.string().min(1, "Code is required"),
  output_weight_kg: z.number({ error: "Output weight is required" }).positive("Must be greater than 0"),
  output_whole_unit_count: z.number().int().positive().optional(),
});

export type GradingOutputFormValues = z.infer<typeof gradingOutputFormSchema>;

export const DEFAULT_GRADING_OUTPUT_FORM_VALUES: GradingOutputFormValues = {
  grade_definition_version_id: "",
  grade_definition_label: "",
  code: "",
  output_weight_kg: 0,
  output_whole_unit_count: undefined,
};

export const recordGradingFormSchema = z
  .object({
    source_harvested_produce_lot_id: z.string().min(1, "Select a Harvested Produce Lot"),
    source_produce_lot_code: z.string(),
    processing_hall_location_id: z.string().min(1, "Select a processing location"),
    effective_date: z.string().min(1, "Date is required"),
    effective_time_of_day: z.string().min(1, "Time is required"),
    note: z.string(),
    count_mode: z.boolean(),
    input_presented_weight_kg: z.number({ error: "Input presented weight is required" }).positive("Must be greater than 0"),
    input_presented_whole_unit_count: z.number().int().positive().optional(),
    rejected_weight_kg: z.number().min(0, "Cannot be negative"),
    rejected_whole_unit_count: z.number().int().min(0).optional(),
    loss_weight_kg: z.number().min(0, "Cannot be negative"),
    loss_whole_unit_count: z.number().int().min(0).optional(),
    sample_weight_kg: z.number().min(0, "Cannot be negative"),
    sample_whole_unit_count: z.number().int().min(0).optional(),
    remainder_weight_kg: z.number().min(0, "Cannot be negative"),
    remainder_whole_unit_count: z.number().int().min(0).optional(),
    outputs: z.array(gradingOutputFormSchema).min(1, "Add at least one graded output"),
  })
  .superRefine((values, ctx) => {
    const codes = values.outputs.map((o) => o.code.trim().toUpperCase());
    const dupCodes = new Set(codes.filter((c, i) => codes.indexOf(c) !== i));
    if (dupCodes.size > 0) {
      ctx.addIssue({ code: z.ZodIssueCode.custom, path: ["outputs"], message: "Output codes must be unique" });
    }
    const versions = values.outputs.map((o) => o.grade_definition_version_id);
    const dupVersions = new Set(versions.filter((v, i) => versions.indexOf(v) !== i));
    if (dupVersions.size > 0) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom, path: ["outputs"], message: "The same grade was selected more than once",
      });
    }

    const outputWeightSum = values.outputs.reduce((sum, o) => sum + (o.output_weight_kg || 0), 0);
    const accountedWeight =
      values.rejected_weight_kg + values.loss_weight_kg + values.sample_weight_kg + values.remainder_weight_kg
      + outputWeightSum;
    if (Math.abs(accountedWeight - values.input_presented_weight_kg) > WEIGHT_EPSILON) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["remainder_weight_kg"],
        message: `Rejection + loss + sample + remainder + graded outputs (${accountedWeight.toFixed(3)} kg) must equal input presented (${values.input_presented_weight_kg.toFixed(3)} kg)`,
      });
    }

    if (!values.count_mode) return;
    if (values.input_presented_whole_unit_count == null) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom, path: ["input_presented_whole_unit_count"], message: "Count is required",
      });
    }
    for (const [i, output] of values.outputs.entries()) {
      if (output.output_whole_unit_count == null) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom, path: ["outputs", i, "output_whole_unit_count"], message: "Count is required",
        });
      }
    }
    const outputCountSum = values.outputs.reduce((sum, o) => sum + (o.output_whole_unit_count || 0), 0);
    const accountedCount =
      (values.rejected_whole_unit_count ?? 0) + (values.loss_whole_unit_count ?? 0)
      + (values.sample_whole_unit_count ?? 0) + (values.remainder_whole_unit_count ?? 0) + outputCountSum;
    if (values.input_presented_whole_unit_count != null && accountedCount !== values.input_presented_whole_unit_count) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["remainder_whole_unit_count"],
        message: `Rejection + loss + sample + remainder + graded outputs (${accountedCount}) must equal input presented count (${values.input_presented_whole_unit_count})`,
      });
    }
  });

export type RecordGradingFormValues = z.infer<typeof recordGradingFormSchema>;
