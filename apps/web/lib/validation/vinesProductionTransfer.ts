import { z } from "zod";

import type { VinesProductionTransferCreate } from "@/lib/api/client";

/** VINES-OPS-001B: Vines Production Transfer -- one InterVines (Batch,
 * Table) source group to a server-allocated pool of Grow Bag(s) on free
 * Grow Bag Position(s) under one Grow Gutter, one atomic composite command.
 * Mirrors `intervinesTransplant.ts`'s own pool/quantity-based shape
 * (never a destination-picker-based N×M matrix) on BOTH sides now: the
 * operator names a source group and a plant count (never an individual
 * Grow Cube), and a destination Gutter plus a REQUIRED Grow Bag
 * specification (never an individual Grow Bag or Position). No loss/
 * damage/rejection/sample fields are collected here at all -- the ticket is
 * explicit that "No biological loss is implied" by this transfer. */

export const MAX_PLANT_COUNT = 200; // mirrors the backend's MAX_SOURCE_LINES

export const vinesProductionTransferFormSchema = z
  .object({
    batch_id: z.string(),
    batch_code: z.string(),
    crop_common_name: z.string(),
    variety_name: z.string(),
    source_intervines_table_id: z.string().min(1, "Select an InterVines source"),
    source_table_code: z.string(),
    current_available: z.number(),
    destination_greenhouse_id: z.string(),
    destination_grow_gutter_id: z.string().min(1, "Grow Gutter is required"),
    gutter_code: z.string(),
    grow_bag_specification_id: z.string().min(1, "Grow Bag specification is required"),
    plant_count: z
      .number({ error: "Plant count is required" })
      .int("Must be a whole number")
      .positive("Must be greater than 0")
      .max(MAX_PLANT_COUNT, `Cannot exceed ${MAX_PLANT_COUNT} plants per command`),
    available_plant_capacity: z.number(),
    effective_date: z.string().min(1, "Date is required"),
    effective_time_of_day: z.string().min(1, "Time is required"),
    note: z.string(),
  })
  .superRefine((values, ctx) => {
    if (values.plant_count > values.current_available) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom, path: ["plant_count"],
        message: `Cannot exceed this InterVines source's available plants (${values.current_available})`,
      });
    }
    if (values.plant_count > values.available_plant_capacity) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom, path: ["plant_count"],
        message: `Cannot exceed the available Grow Bag capacity (${values.available_plant_capacity})`,
      });
    }
  });
export type VinesProductionTransferFormValues = z.infer<typeof vinesProductionTransferFormSchema>;

export const DEFAULT_VINES_PRODUCTION_TRANSFER_FORM_VALUES: VinesProductionTransferFormValues = {
  batch_id: "", batch_code: "", crop_common_name: "", variety_name: "",
  source_intervines_table_id: "", source_table_code: "", current_available: 0,
  destination_greenhouse_id: "", destination_grow_gutter_id: "", gutter_code: "",
  grow_bag_specification_id: "", plant_count: 0, available_plant_capacity: 0,
  effective_date: "", effective_time_of_day: "", note: "",
};

export function buildVinesProductionTransferPayload(
  values: VinesProductionTransferFormValues,
  clientCommandId: string,
): VinesProductionTransferCreate {
  const effectiveTime = new Date(`${values.effective_date}T${values.effective_time_of_day}`).toISOString();
  return {
    client_command_id: clientCommandId,
    effective_time: effectiveTime,
    note: values.note.trim() || null,
    source_intervines_table_id: values.source_intervines_table_id,
    plant_count: values.plant_count,
    destination_grow_gutter_id: values.destination_grow_gutter_id,
    grow_bag_specification_id: values.grow_bag_specification_id,
  };
}
