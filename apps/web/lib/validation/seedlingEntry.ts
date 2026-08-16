import { z } from "zod";

import type { SeedlingEntryCreate } from "@/lib/api/client";

/** NURSERY-OPS-003A: Seedling Entry & Placement -- the operator supplies
 * only physical/handoff-command facts (Tray, destination Seedling Table,
 * effective time). `starting_living_seedling_count` and the source
 * Germination snapshot are never sent by the client; the server always
 * resolves and freezes them authoritatively. Mirrors germination.ts's
 * two-phase configure/review pattern and date+time-of-day convention. */

export const seedlingEntryFormSchema = z.object({
  batch_carrier_assignment_id: z.string().min(1, "Seed Tray is required"),
  destination_seedling_table_id: z.string().min(1, "Seedling Table is required"),
  effective_date: z.string().min(1, "Date is required"),
  effective_time_of_day: z.string().min(1, "Time is required"),
  reason: z.string(),
});
export type SeedlingEntryFormValues = z.infer<typeof seedlingEntryFormSchema>;

export const DEFAULT_SEEDLING_ENTRY_FORM_VALUES: SeedlingEntryFormValues = {
  batch_carrier_assignment_id: "",
  destination_seedling_table_id: "",
  effective_date: "",
  effective_time_of_day: "",
  reason: "",
};

export function buildSeedlingEntryPayload(
  values: SeedlingEntryFormValues,
  clientCommandId: string,
): SeedlingEntryCreate {
  return {
    client_command_id: clientCommandId,
    batch_carrier_assignment_id: values.batch_carrier_assignment_id,
    destination_seedling_table_id: values.destination_seedling_table_id,
    effective_time: new Date(`${values.effective_date}T${values.effective_time_of_day}`).toISOString(),
    reason: values.reason.trim() || null,
  };
}
