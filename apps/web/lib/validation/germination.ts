import { z } from "zod";

import type { PlaceTrayCreate, PlaceTrolleyCreate } from "@/lib/api/client";

/** NURSERY-OPS-002A / PILOT-UX-001B: Germination Placement -- physical
 * placement only (a Germination Trolley Asset occupies a Germination
 * Chamber Location directly; a Seed Tray Carrier occupies a Trolley Level
 * directly, or one of that Level's legacy Slots). No biological Germination
 * outcome field belongs in either form. Mirrors nursery.ts's two-phase
 * configure/review pattern and date+time-of-day convention. */

export const placeTrolleyFormSchema = z.object({
  trolley_id: z.string().min(1, "Trolley is required"),
  chamber_id: z.string().min(1, "Germination Chamber is required"),
  effective_date: z.string().min(1, "Date is required"),
  effective_time_of_day: z.string().min(1, "Time is required"),
  reason: z.string(),
});
export type PlaceTrolleyFormValues = z.infer<typeof placeTrolleyFormSchema>;

export const DEFAULT_PLACE_TROLLEY_FORM_VALUES: PlaceTrolleyFormValues = {
  trolley_id: "",
  chamber_id: "",
  effective_date: "",
  effective_time_of_day: "",
  reason: "",
};

export function buildPlaceTrolleyPayload(
  values: PlaceTrolleyFormValues,
  clientCommandId: string,
): PlaceTrolleyCreate {
  return {
    client_command_id: clientCommandId,
    trolley_id: values.trolley_id,
    chamber_id: values.chamber_id,
    effective_time: new Date(`${values.effective_date}T${values.effective_time_of_day}`).toISOString(),
    reason: values.reason.trim() || null,
  };
}

export const placeTrayFormSchema = z.object({
  tray_id: z.string().min(1, "Seed Tray is required"),
  trolley_id: z.string().min(1, "Trolley is required"),
  asset_position_id: z.string().min(1, "Level is required"),
  effective_date: z.string().min(1, "Date is required"),
  effective_time_of_day: z.string().min(1, "Time is required"),
  reason: z.string(),
});
export type PlaceTrayFormValues = z.infer<typeof placeTrayFormSchema>;

export const DEFAULT_PLACE_TRAY_FORM_VALUES: PlaceTrayFormValues = {
  tray_id: "",
  trolley_id: "",
  asset_position_id: "",
  effective_date: "",
  effective_time_of_day: "",
  reason: "",
};

export function buildPlaceTrayPayload(values: PlaceTrayFormValues, clientCommandId: string): PlaceTrayCreate {
  return {
    client_command_id: clientCommandId,
    tray_id: values.tray_id,
    trolley_id: values.trolley_id,
    asset_position_id: values.asset_position_id,
    effective_time: new Date(`${values.effective_date}T${values.effective_time_of_day}`).toISOString(),
    reason: values.reason.trim() || null,
  };
}
