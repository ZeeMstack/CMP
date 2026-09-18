import { z } from "zod";

import type { RecordBatchHarvestForecast } from "@/lib/api/client";

/** PILOT-PLAN-001B: Record/Revise Batch Harvest Forecast. Quantities are
 * plain decimal-string inputs (never `valueAsNumber`), mirroring
 * `lib/validation/planning.ts`'s own rationale -- the backend parses the
 * string itself, so a JS float round-trip never touches it. */

const NOTES_MAX = 2000;

// FORECAST_BASES per app/schemas/harvest_forecast.py -- deliberately no
// "ai_prediction" value (see docs/domain/HARVEST_FORECAST_CAPACITY_MODEL.md
// Part 3).
export const FORECAST_BASIS_OPTIONS = [
  { value: "grower_estimate", label: "Grower estimate" },
  { value: "planning_assumption", label: "Planning assumption" },
  { value: "protocol_guidance", label: "Protocol guidance" },
] as const;

function quantityField(label: string) {
  return z
    .string()
    .trim()
    .min(1, `${label} is required`)
    .refine((v) => /^\d+(\.\d+)?$/.test(v), { message: `${label} must be a positive number` });
}

export const harvestForecastFormSchema = z
  .object({
    window_start_date: z.string().min(1, "Window start is required"),
    window_end_date: z.string().min(1, "Window end is required"),
    low_quantity: quantityField("Low"),
    expected_quantity: quantityField("Expected").refine((v) => Number(v) > 0, { message: "Expected must be greater than zero" }),
    high_quantity: quantityField("High"),
    quantity_uom_id: z.string().min(1, "Unit is required"),
    basis: z.enum(["grower_estimate", "planning_assumption", "protocol_guidance"], {
      error: "Basis is required",
    }),
    notes: z.string().max(NOTES_MAX, `Notes must be ${NOTES_MAX} characters or fewer`),
    revision_reason: z.string().max(NOTES_MAX, `Revision reason must be ${NOTES_MAX} characters or fewer`),
  })
  .refine((v) => v.window_end_date >= v.window_start_date, {
    message: "Window end must be on or after window start",
    path: ["window_end_date"],
  })
  .refine((v) => Number(v.low_quantity) <= Number(v.expected_quantity), {
    message: "Low must be less than or equal to Expected",
    path: ["low_quantity"],
  })
  .refine((v) => Number(v.expected_quantity) <= Number(v.high_quantity), {
    message: "Expected must be less than or equal to High",
    path: ["high_quantity"],
  });

export type HarvestForecastFormValues = z.infer<typeof harvestForecastFormSchema>;

export const DEFAULT_HARVEST_FORECAST_FORM_VALUES: HarvestForecastFormValues = {
  window_start_date: "",
  window_end_date: "",
  low_quantity: "",
  expected_quantity: "",
  high_quantity: "",
  quantity_uom_id: "",
  basis: "grower_estimate",
  notes: "",
  revision_reason: "",
};

export function buildRecordHarvestForecastPayload(
  values: HarvestForecastFormValues,
  clientCommandId: string,
): RecordBatchHarvestForecast {
  return {
    client_command_id: clientCommandId,
    window_start_date: values.window_start_date,
    window_end_date: values.window_end_date,
    low_quantity: values.low_quantity,
    expected_quantity: values.expected_quantity,
    high_quantity: values.high_quantity,
    quantity_uom_id: values.quantity_uom_id,
    basis: values.basis,
    effective_time: new Date().toISOString(),
    notes: values.notes.trim() || null,
    revision_reason: values.revision_reason.trim() || null,
  };
}
