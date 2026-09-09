import { z } from "zod";

/** VINES-OPS-002: Record Plant Loss for Vines Production -- unlike Leafy's
 * bare count (`lib/validation/productionDisposition.ts`), the operator must
 * name the SPECIFIC Grow Cube(s) actually lost (one living plant each).
 * Includes `culled` (the ticket's own example reason with no Leafy
 * equivalent) alongside every reason LEAFY-OPS-001 already established --
 * one shared, platform-wide reason catalog (see the `ecedd713789a`
 * migration). */

export const VINES_DISPOSITION_REASONS = [
  { code: "dead", label: "Dead" },
  { code: "disease_removal", label: "Disease" },
  { code: "pest_damage", label: "Pest damage" },
  { code: "mechanical_damage", label: "Mechanical damage" },
  { code: "quality_removal", label: "Quality removal" },
  { code: "culled", label: "Culled" },
  { code: "other", label: "Other" },
] as const;

export const recordGrowCubeLossFormSchema = z
  .object({
    batch_carrier_assignment_id: z.string().min(1, "Select a Grow Bag"),
    grow_bag_code: z.string(),
    living_plant_count: z.number(),
    grow_cube_carrier_ids: z.array(z.string()).min(1, "Select at least one affected plant"),
    reason_code: z.string().min(1, "Reason is required"),
    note: z.string(),
    effective_date: z.string().min(1, "Date is required"),
    effective_time_of_day: z.string().min(1, "Time is required"),
  })
  .superRefine((values, ctx) => {
    if (values.reason_code === "other" && values.note.trim().length === 0) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom, path: ["note"], message: "A note is required when reason is Other",
      });
    }
    if (values.grow_cube_carrier_ids.length > values.living_plant_count) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom, path: ["grow_cube_carrier_ids"],
        message: `Selected plants (${values.grow_cube_carrier_ids.length}) exceed current living plants (${values.living_plant_count})`,
      });
    }
  });

export type RecordGrowCubeLossFormValues = z.infer<typeof recordGrowCubeLossFormSchema>;

export const DEFAULT_RECORD_GROW_CUBE_LOSS_FORM_VALUES: Omit<
  RecordGrowCubeLossFormValues,
  "batch_carrier_assignment_id" | "grow_bag_code" | "living_plant_count"
> = {
  grow_cube_carrier_ids: [],
  reason_code: "",
  note: "",
  effective_date: "",
  effective_time_of_day: "",
};
