import { z } from "zod";

/** PILOT-SETUP-001B7: shared activate/retire form shape for
 * GradeDefinitionVersion and PackSpecificationVersion -- both backend
 * commands take the exact same payload shape (`client_command_id` +
 * tz-aware `effective_time`), so this is the one place that shape is
 * defined, rather than duplicating it per resource. Date + time-of-day
 * inputs mirror the existing NURSERY-OPS-002A convention (`germination.ts`)
 * rather than a single datetime-local input. */
export const effectiveTimeActionFormSchema = z.object({
  effective_date: z.string().min(1, "Date is required"),
  effective_time_of_day: z.string().min(1, "Time is required"),
});
export type EffectiveTimeActionFormValues = z.infer<typeof effectiveTimeActionFormSchema>;

function pad(n: number): string {
  return String(n).padStart(2, "0");
}

/** Defaults the picker to "now" (local time) -- both activation and
 * retirement reject a future `effective_time`, so "now" is always a valid
 * starting point an operator can immediately submit or backdate from. */
export function nowEffectiveTimeActionDefaults(): EffectiveTimeActionFormValues {
  const now = new Date();
  return {
    effective_date: `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`,
    effective_time_of_day: `${pad(now.getHours())}:${pad(now.getMinutes())}`,
  };
}

export function buildEffectiveTimeIso(values: EffectiveTimeActionFormValues): string {
  return new Date(`${values.effective_date}T${values.effective_time_of_day}`).toISOString();
}

/** Builds the exact `{ client_command_id, effective_time }` shape both
 * `GradeDefinitionVersionActivate`/`Retire` and
 * `PackSpecificationVersionActivate`/`Retire` require. */
export function buildEffectiveTimeActionPayload(
  values: EffectiveTimeActionFormValues,
  clientCommandId: string,
): { client_command_id: string; effective_time: string } {
  return { client_command_id: clientCommandId, effective_time: buildEffectiveTimeIso(values) };
}
