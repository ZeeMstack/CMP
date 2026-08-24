import { z } from "zod";

/** LEAFY-OPS-001: Record Plant Loss (Production Biological Disposition) --
 * the operator supplies only a positive plant-loss count, a reason, and an
 * optional note; the backend computes the signed delta. Mirrors the
 * validation shape of `lib/validation/leafyProductionTransfer.ts`'s own
 * frozen fields (reason "other" requires a note). */

export const PRODUCTION_DISPOSITION_REASONS = [
  { code: "dead", label: "Dead" },
  { code: "disease_removal", label: "Disease" },
  { code: "pest_damage", label: "Pest damage" },
  { code: "mechanical_damage", label: "Mechanical damage" },
  { code: "quality_removal", label: "Quality removal" },
  { code: "other", label: "Other" },
] as const;

export const recordPlantLossFormSchema = z
  .object({
    batch_carrier_assignment_id: z.string().min(1, "Select a Production Plate"),
    plate_code: z.string(),
    current_living_population: z.number(),
    plant_loss_count: z
      .number({ error: "Loss count is required" })
      .int("Must be a whole number")
      .positive("Must be greater than 0"),
    reason_code: z.string().min(1, "Reason is required"),
    note: z.string(),
    effective_date: z.string().min(1, "Date is required"),
    effective_time_of_day: z.string().min(1, "Time is required"),
  })
  .superRefine((values, ctx) => {
    if (values.reason_code === "other" && values.note.trim().length === 0) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["note"],
        message: "A note is required when reason is Other",
      });
    }
    if (values.plant_loss_count > values.current_living_population) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["plant_loss_count"],
        message: `Loss count (${values.plant_loss_count}) exceeds current living population (${values.current_living_population})`,
      });
    }
  });

export type RecordPlantLossFormValues = z.infer<typeof recordPlantLossFormSchema>;

export const DEFAULT_RECORD_PLANT_LOSS_FORM_VALUES: Omit<
  RecordPlantLossFormValues,
  "batch_carrier_assignment_id" | "plate_code" | "current_living_population"
> = {
  plant_loss_count: 0,
  reason_code: "",
  note: "",
  effective_date: "",
  effective_time_of_day: "",
};

export const correctPlantLossFormSchema = z
  .object({
    mode: z.enum(["void", "replace"]),
    plant_loss_count: z.number().int().positive().optional(),
    reason_code: z.string().optional(),
    note: z.string().optional(),
    effective_date: z.string().optional(),
    effective_time_of_day: z.string().optional(),
  })
  .superRefine((values, ctx) => {
    if (values.mode !== "replace") return;
    if (!values.plant_loss_count || values.plant_loss_count <= 0) {
      ctx.addIssue({ code: z.ZodIssueCode.custom, path: ["plant_loss_count"], message: "Corrected loss count is required" });
    }
    if (!values.reason_code) {
      ctx.addIssue({ code: z.ZodIssueCode.custom, path: ["reason_code"], message: "Reason is required" });
    }
    if (values.reason_code === "other" && !(values.note ?? "").trim()) {
      ctx.addIssue({ code: z.ZodIssueCode.custom, path: ["note"], message: "A note is required when reason is Other" });
    }
    if (!values.effective_date || !values.effective_time_of_day) {
      ctx.addIssue({ code: z.ZodIssueCode.custom, path: ["effective_date"], message: "Date and time are required" });
    }
  });

export type CorrectPlantLossFormValues = z.infer<typeof correctPlantLossFormSchema>;
