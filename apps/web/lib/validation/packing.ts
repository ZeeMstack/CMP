import { z } from "zod";

/** POSTHARVEST-OPS-001G: Record Packing (one or more input Graded Produce
 * Lots, one Finished Goods Lot output, reconciliation against process
 * loss/rejection). Client-side validation is convenience only -- the server
 * remains the sole authority (mirrors `lib/validation/grading.ts`'s own
 * shape). Packing has no sample/remainder split (see `PackingEventCreate`):
 * total consumed input = packed output + process loss + rejected. */

const WEIGHT_EPSILON = 0.001;

export const packingInputLineFormSchema = z.object({
  graded_produce_lot_id: z.string().min(1),
  graded_produce_lot_code: z.string(),
  available_weight_kg: z.number(),
  available_whole_unit_count: z.number().nullable(),
  consumed_weight_kg: z.number({ error: "Consumed weight is required" }).positive("Must be greater than 0"),
  consumed_whole_unit_count: z.number().int().positive().optional(),
  note: z.string(),
});

export type PackingInputLineFormValues = z.infer<typeof packingInputLineFormSchema>;

export const recordPackingFormSchema = z
  .object({
    pack_specification_version_id: z.string().min(1, "Select a Pack Specification version"),
    pack_specification_label: z.string(),
    effective_date: z.string().min(1, "Date is required"),
    effective_time_of_day: z.string().min(1, "Time is required"),
    finished_goods_lot_code: z.string().min(1, "Finished Goods Lot code is required"),
    package_count: z.number({ error: "Package count is required" }).int().positive("Must be greater than 0"),
    packed_output_weight_kg: z.number({ error: "Packed output weight is required" }).positive("Must be greater than 0"),
    process_loss_weight_kg: z.number().min(0, "Cannot be negative"),
    rejected_weight_kg: z.number().min(0, "Cannot be negative"),
    note: z.string(),
    count_mode: z.boolean(),
    input_lines: z.array(packingInputLineFormSchema).min(1, "Add at least one Graded Produce Lot").max(50),
  })
  .superRefine((values, ctx) => {
    const ids = values.input_lines.map((l) => l.graded_produce_lot_id);
    const dupIds = new Set(ids.filter((id, i) => ids.indexOf(id) !== i));
    if (dupIds.size > 0) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom, path: ["input_lines"], message: "The same Graded Produce Lot was added more than once",
      });
    }
    values.input_lines.forEach((line, i) => {
      if (line.consumed_weight_kg > line.available_weight_kg + WEIGHT_EPSILON) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: ["input_lines", i, "consumed_weight_kg"],
          message: `Exceeds available balance (${line.available_weight_kg} kg) for ${line.graded_produce_lot_code}`,
        });
      }
    });

    const consumedSum = values.input_lines.reduce((sum, l) => sum + (l.consumed_weight_kg || 0), 0);
    const accounted = values.packed_output_weight_kg + values.process_loss_weight_kg + values.rejected_weight_kg;
    if (Math.abs(consumedSum - accounted) > WEIGHT_EPSILON) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["process_loss_weight_kg"],
        message: `Packed output + process loss + rejection (${accounted.toFixed(3)} kg) must equal total consumed input (${consumedSum.toFixed(3)} kg)`,
      });
    }

    if (!values.count_mode) return;
    values.input_lines.forEach((line, i) => {
      if (line.consumed_whole_unit_count == null) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom, path: ["input_lines", i, "consumed_whole_unit_count"], message: "Count is required",
        });
      } else if (line.available_whole_unit_count != null && line.consumed_whole_unit_count > line.available_whole_unit_count) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: ["input_lines", i, "consumed_whole_unit_count"],
          message: `Exceeds available balance (${line.available_whole_unit_count}) for ${line.graded_produce_lot_code}`,
        });
      }
    });
  });

export type RecordPackingFormValues = z.infer<typeof recordPackingFormSchema>;
