import { z } from "zod";

/** HARVEST-OPS-001 SLICE 2: Record Leafy Harvest (multi-Plate, one CropBatch)
 * and line-level correction. Client-side validation is convenience only --
 * the server remains the sole authority (mirrors `lib/validation/
 * productionDisposition.ts`'s own established shape and comment). */

export const HARVEST_CORRECTION_REASONS = [
  { code: "miscounted", label: "Miscounted" },
  { code: "weighing_error", label: "Weighing error" },
  { code: "data_entry_error", label: "Data entry error" },
  { code: "other", label: "Other" },
] as const;

export const leafyHarvestLineFormSchema = z
  .object({
    batch_carrier_assignment_id: z.string().min(1),
    production_plate_code: z.string(),
    current_living_heads: z.number(),
    heads_harvested: z
      .number({ error: "Heads harvested is required" })
      .int("Must be a whole number")
      .positive("Must be greater than 0"),
    raw_harvested_weight_kg: z.number({ error: "Raw harvested weight is required" }).positive("Must be greater than 0"),
    note: z.string(),
  })
  .superRefine((values, ctx) => {
    if (values.heads_harvested > values.current_living_heads) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["heads_harvested"],
        message: `Heads harvested (${values.heads_harvested}) exceeds current living population (${values.current_living_heads})`,
      });
    }
  });

export type LeafyHarvestLineFormValues = z.infer<typeof leafyHarvestLineFormSchema>;

export const recordLeafyHarvestFormSchema = z
  .object({
    batch_id: z.string().min(1, "Select a Production Plate to establish the Batch"),
    batch_code: z.string(),
    effective_date: z.string().min(1, "Date is required"),
    effective_time_of_day: z.string().min(1, "Time is required"),
    note: z.string(),
    lines: z.array(leafyHarvestLineFormSchema).min(1, "Select at least one Production Plate"),
  })
  .superRefine((values, ctx) => {
    const ids = values.lines.map((l) => l.batch_carrier_assignment_id);
    const duplicates = new Set(ids.filter((id, i) => ids.indexOf(id) !== i));
    if (duplicates.size > 0) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["lines"],
        message: "The same Production Plate was selected more than once",
      });
    }
  });

export type RecordLeafyHarvestFormValues = z.infer<typeof recordLeafyHarvestFormSchema>;

export const DEFAULT_LEAFY_HARVEST_LINE_FORM_VALUES: Omit<
  LeafyHarvestLineFormValues,
  "batch_carrier_assignment_id" | "production_plate_code" | "current_living_heads"
> = {
  heads_harvested: 0,
  raw_harvested_weight_kg: 0,
  note: "",
};

export const correctLeafyHarvestFormSchema = z
  .object({
    mode: z.enum(["void", "replace"]),
    current_whole_unit_count: z.number(),
    current_harvested_weight_kg: z.number(),
    corrected_whole_unit_count: z.number().int().positive().optional(),
    corrected_harvested_weight_kg: z.number().positive().optional(),
    reason_code: z.string(),
    note: z.string(),
  })
  .superRefine((values, ctx) => {
    if (!values.reason_code) {
      ctx.addIssue({ code: z.ZodIssueCode.custom, path: ["reason_code"], message: "Reason is required" });
    }
    if (!values.note.trim()) {
      ctx.addIssue({ code: z.ZodIssueCode.custom, path: ["note"], message: "An explanation note is required" });
    }
    if (values.mode !== "replace") return;
    if (!values.corrected_whole_unit_count || values.corrected_whole_unit_count <= 0) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom, path: ["corrected_whole_unit_count"], message: "Corrected heads harvested is required",
      });
    }
    if (!values.corrected_harvested_weight_kg || values.corrected_harvested_weight_kg <= 0) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom, path: ["corrected_harvested_weight_kg"], message: "Corrected raw weight is required",
      });
    }
    if (
      values.corrected_whole_unit_count === values.current_whole_unit_count
      && values.corrected_harvested_weight_kg === values.current_harvested_weight_kg
    ) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom, path: ["corrected_whole_unit_count"],
        message: "Change at least the heads harvested or the raw weight from the current effective values",
      });
    }
  });

export type CorrectLeafyHarvestFormValues = z.infer<typeof correctLeafyHarvestFormSchema>;
