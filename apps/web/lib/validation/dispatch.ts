import { z } from "zod";

/** PILOT-READY-001: Record Dispatch (one or more Finished Goods Lots,
 * consuming only their currently-unplaced balance -- CMP-018 -- plus one
 * factual dispatch-level temperature reading). Client-side validation is
 * convenience only -- the server remains the sole authority (mirrors
 * `lib/validation/packing.ts`'s own shape). */

const WEIGHT_EPSILON = 0.001;
const MIN_TEMPERATURE_C = -100;
const MAX_TEMPERATURE_C = 100;

export const dispatchLineFormSchema = z.object({
  finished_goods_lot_id: z.string().min(1),
  finished_goods_lot_code: z.string(),
  available_weight_kg: z.number(),
  available_package_count: z.number(),
  dispatched_weight_kg: z.number({ error: "Dispatched weight is required" }).positive("Must be greater than 0"),
  dispatched_package_count: z.number({ error: "Dispatched package count is required" }).int().positive("Must be greater than 0"),
});

export type DispatchLineFormValues = z.infer<typeof dispatchLineFormSchema>;

export const recordDispatchFormSchema = z
  .object({
    code: z.string().min(1, "Dispatch code is required"),
    effective_date: z.string().min(1, "Date is required"),
    effective_time_of_day: z.string().min(1, "Time is required"),
    dispatch_temperature_c: z
      .number({ error: "Dispatch temperature is required" })
      .gt(MIN_TEMPERATURE_C, "Outside the supported range")
      .lt(MAX_TEMPERATURE_C, "Outside the supported range"),
    external_reference: z.string(),
    note: z.string(),
    lines: z.array(dispatchLineFormSchema).min(1, "Add at least one Finished Goods Lot").max(50),
  })
  .superRefine((values, ctx) => {
    const ids = values.lines.map((l) => l.finished_goods_lot_id);
    const dupIds = new Set(ids.filter((id, i) => ids.indexOf(id) !== i));
    if (dupIds.size > 0) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom, path: ["lines"], message: "The same Finished Goods Lot was added more than once",
      });
    }
    values.lines.forEach((line, i) => {
      if (line.dispatched_weight_kg > line.available_weight_kg + WEIGHT_EPSILON) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: ["lines", i, "dispatched_weight_kg"],
          message: `Exceeds unplaced balance (${line.available_weight_kg} kg) for ${line.finished_goods_lot_code}`,
        });
      }
      if (line.dispatched_package_count > line.available_package_count) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: ["lines", i, "dispatched_package_count"],
          message: `Exceeds unplaced balance (${line.available_package_count} pkg) for ${line.finished_goods_lot_code}`,
        });
      }
    });
  });

export type RecordDispatchFormValues = z.infer<typeof recordDispatchFormSchema>;
