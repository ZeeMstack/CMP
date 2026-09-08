import { z } from "zod";

import type { IntervinesTransplantCreate } from "@/lib/api/client";

/** VINES-OPS-001A: InterVines Transplant -- a single Seedling source Tray to
 * a server-allocated pool of Grow Cube(s) on one InterVines Table, one
 * atomic composite command. Deliberately quantity/pool-based, not a
 * destination-picker-based N×M allocation matrix like InterSalads' own form
 * -- the ticket's frozen compact UX names one source, one Table, and a plant
 * count; the server chooses which Grow Cubes to use. No loss/damage/
 * rejection/sample fields are collected here at all (the ticket is explicit
 * this workflow "does NOT record a biological loss"). */

export const MAX_PLANT_COUNT = 500; // mirrors the backend's MAX_DESTINATION_LINES

export const intervinesTransplantFormSchema = z
  .object({
    batch_id: z.string(),
    batch_code: z.string(),
    crop_common_name: z.string(),
    variety_name: z.string(),
    source_assignment_id: z.string().min(1, "Select a source Tray"),
    tray_code: z.string(),
    current_available: z.number(),
    destination_location_id: z.string().min(1, "InterVines Table is required"),
    table_code: z.string(),
    grow_cube_specification_id: z.string(),
    plant_count: z
      .number({ error: "Plant count is required" })
      .int("Must be a whole number")
      .positive("Must be greater than 0")
      .max(MAX_PLANT_COUNT, `Cannot exceed ${MAX_PLANT_COUNT} plants per command`),
    available_grow_cubes: z.number(),
    effective_date: z.string().min(1, "Date is required"),
    effective_time_of_day: z.string().min(1, "Time is required"),
    note: z.string(),
  })
  .superRefine((values, ctx) => {
    if (values.plant_count > values.current_available) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom, path: ["plant_count"],
        message: `Cannot exceed this source's available seedlings (${values.current_available})`,
      });
    }
    if (values.plant_count > values.available_grow_cubes) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom, path: ["plant_count"],
        message: `Cannot exceed the available Grow Cubes (${values.available_grow_cubes})`,
      });
    }
  });
export type IntervinesTransplantFormValues = z.infer<typeof intervinesTransplantFormSchema>;

export const DEFAULT_INTERVINES_TRANSPLANT_FORM_VALUES: IntervinesTransplantFormValues = {
  batch_id: "", batch_code: "", crop_common_name: "", variety_name: "",
  source_assignment_id: "", tray_code: "", current_available: 0,
  destination_location_id: "", table_code: "", grow_cube_specification_id: "",
  plant_count: 0, available_grow_cubes: 0,
  effective_date: "", effective_time_of_day: "", note: "",
};

export function buildIntervinesTransplantPayload(
  values: IntervinesTransplantFormValues,
  clientCommandId: string,
): IntervinesTransplantCreate {
  const effectiveTime = new Date(`${values.effective_date}T${values.effective_time_of_day}`).toISOString();
  return {
    client_command_id: clientCommandId,
    effective_time: effectiveTime,
    note: values.note.trim() || null,
    source_assignment_id: values.source_assignment_id,
    plant_count: values.plant_count,
    destination_location_id: values.destination_location_id,
    grow_cube_specification_id: values.grow_cube_specification_id || null,
  };
}
