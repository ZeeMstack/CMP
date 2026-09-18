import { z } from "zod";

import type { CreateProductionCapacityAllocation, UpdateProductionCapacityAllocation } from "@/lib/api/client";

/** PILOT-PLAN-001B: Create/Update a Production Capacity Allocation.
 * `planned_start_date`/`planned_end_date` are half-open `[start, end)` --
 * see docs/domain/HARVEST_FORECAST_CAPACITY_MODEL.md's Time Semantics --
 * so the form validates `end > start`, strictly, unlike the Harvest
 * Forecast window's inclusive-inclusive `end >= start`. */

const NOTES_MAX = 2000;

function positiveIntegerField(label: string) {
  return z
    .string()
    .trim()
    .min(1, `${label} is required`)
    .refine((v) => /^\d+$/.test(v), { message: `${label} must be a whole number` })
    .refine((v) => Number(v) > 0, { message: `${label} must be greater than zero` });
}

export const capacityAllocationFormSchema = z
  .object({
    location_id: z.string().min(1, "Location is required"),
    production_system_id: z.string(),
    planned_start_date: z.string().min(1, "Start date is required"),
    planned_end_date: z.string().min(1, "End date is required"),
    planned_capacity_amount: positiveIntegerField("Planned positions"),
    source_seeding_program_line_id: z.string(),
    source_crop_batch_id: z.string(),
    notes: z.string().max(NOTES_MAX, `Notes must be ${NOTES_MAX} characters or fewer`),
  })
  .refine((v) => v.planned_end_date > v.planned_start_date, {
    message: "End must be after start (end is exclusive)",
    path: ["planned_end_date"],
  });

export type CapacityAllocationFormValues = z.infer<typeof capacityAllocationFormSchema>;

export const DEFAULT_CAPACITY_ALLOCATION_FORM_VALUES: CapacityAllocationFormValues = {
  location_id: "",
  production_system_id: "",
  planned_start_date: "",
  planned_end_date: "",
  planned_capacity_amount: "",
  source_seeding_program_line_id: "",
  source_crop_batch_id: "",
  notes: "",
};

export function buildCreateCapacityAllocationPayload(
  values: CapacityAllocationFormValues,
  clientCommandId: string,
): CreateProductionCapacityAllocation {
  return {
    client_command_id: clientCommandId,
    location_id: values.location_id,
    production_system_id: values.production_system_id || null,
    planned_start_date: values.planned_start_date,
    planned_end_date: values.planned_end_date,
    planned_capacity_amount: Number(values.planned_capacity_amount),
    source_seeding_program_line_id: values.source_seeding_program_line_id || null,
    source_crop_batch_id: values.source_crop_batch_id || null,
    notes: values.notes.trim() || null,
  };
}

export const capacityAllocationUpdateFormSchema = z
  .object({
    production_system_id: z.string(),
    planned_start_date: z.string().min(1, "Start date is required"),
    planned_end_date: z.string().min(1, "End date is required"),
    planned_capacity_amount: positiveIntegerField("Planned positions"),
    notes: z.string().max(NOTES_MAX, `Notes must be ${NOTES_MAX} characters or fewer`),
  })
  .refine((v) => v.planned_end_date > v.planned_start_date, {
    message: "End must be after start (end is exclusive)",
    path: ["planned_end_date"],
  });

export type CapacityAllocationUpdateFormValues = z.infer<typeof capacityAllocationUpdateFormSchema>;

export function buildUpdateCapacityAllocationPayload(
  values: CapacityAllocationUpdateFormValues,
  clientCommandId: string,
): UpdateProductionCapacityAllocation {
  return {
    client_command_id: clientCommandId,
    production_system_id: values.production_system_id || null,
    planned_start_date: values.planned_start_date,
    planned_end_date: values.planned_end_date,
    planned_capacity_amount: Number(values.planned_capacity_amount),
    notes: values.notes.trim() || null,
  };
}
