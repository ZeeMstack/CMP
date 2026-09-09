import { z } from "zod";

/** VINES-OPS-003: Record Vines Harvest (multi-Gutter, one CropBatch,
 * weight-only) and line-level correction. Client-side validation is
 * convenience only -- the server remains the sole authority (mirrors
 * `lib/validation/leafyHarvest.ts`'s own established shape). No
 * whole_unit_count anywhere -- Vines Harvest is weight-based for the
 * current pilot crops (Cherry Tomato, Color Capsicum). */

export const HARVEST_CORRECTION_REASONS = [
  { code: "scale_error", label: "Scale error" },
  { code: "weighing_error", label: "Weighing error" },
  { code: "data_entry_error", label: "Data entry error" },
  { code: "other", label: "Other" },
] as const;

export const vinesHarvestLineFormSchema = z.object({
  gutter_id: z.string().min(1),
  gutter_code: z.string(),
  living_plant_count: z.number(),
  harvested_weight_kg: z.number({ error: "Raw harvested weight is required" }).positive("Must be greater than 0"),
  note: z.string(),
});

export type VinesHarvestLineFormValues = z.infer<typeof vinesHarvestLineFormSchema>;

export const recordVinesHarvestFormSchema = z
  .object({
    batch_id: z.string().min(1, "Select a Gutter to establish the Batch"),
    batch_code: z.string(),
    effective_date: z.string().min(1, "Date is required"),
    effective_time_of_day: z.string().min(1, "Time is required"),
    note: z.string(),
    lines: z.array(vinesHarvestLineFormSchema).min(1, "Select at least one Gutter"),
  })
  .superRefine((values, ctx) => {
    const ids = values.lines.map((l) => l.gutter_id);
    const duplicates = new Set(ids.filter((id, i) => ids.indexOf(id) !== i));
    if (duplicates.size > 0) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["lines"],
        message: "The same Gutter was selected more than once",
      });
    }
  });

export type RecordVinesHarvestFormValues = z.infer<typeof recordVinesHarvestFormSchema>;

export const DEFAULT_VINES_HARVEST_LINE_FORM_VALUES: Omit<
  VinesHarvestLineFormValues,
  "gutter_id" | "gutter_code" | "living_plant_count"
> = {
  harvested_weight_kg: 0,
  note: "",
};

export const correctVinesHarvestFormSchema = z
  .object({
    mode: z.enum(["void", "replace"]),
    current_harvested_weight_kg: z.number(),
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
    if (!values.corrected_harvested_weight_kg || values.corrected_harvested_weight_kg <= 0) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom, path: ["corrected_harvested_weight_kg"], message: "Corrected raw weight is required",
      });
    }
    if (values.corrected_harvested_weight_kg === values.current_harvested_weight_kg) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom, path: ["corrected_harvested_weight_kg"],
        message: "Change the raw weight from the current effective value",
      });
    }
  });

export type CorrectVinesHarvestFormValues = z.infer<typeof correctVinesHarvestFormSchema>;
