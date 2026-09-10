import { z } from "zod";

import type {
  ProductionRequirementCreate,
  ProductionRequirementUpdate,
  SeedingProgramLineCreate,
  SeedingProgramLineUpdate,
} from "@/lib/api/client";

/** PLANNING-OPS-001: Production Requirement (crop demand) and Seeding
 * Program Line (planned sowing) forms. `required_quantity`/`planned_
 * quantity`/`expected_coverage_quantity` are plain decimal-string inputs
 * (never `valueAsNumber`) so the payload never loses precision to a JS
 * float round-trip -- the backend parses the string itself. */

const NOTES_MAX = 2000;
const REFERENCE_MAX = 200;

function decimalString(label: string) {
  return z
    .string()
    .trim()
    .min(1, `${label} is required`)
    .refine((v) => /^\d+(\.\d+)?$/.test(v), { message: `${label} must be a positive number` })
    .refine((v) => Number(v) > 0, { message: `${label} must be greater than zero` });
}

// --- Production Requirement ----------------------------------------------------------

export const requirementFormSchema = z.object({
  crop_id: z.string().min(1, "Crop is required"),
  variety_id: z.string(),
  required_by_date: z.string().min(1, "Required-by date is required"),
  required_quantity: decimalString("Quantity"),
  quantity_uom_id: z.string().min(1, "Unit is required"),
  reference: z.string().max(REFERENCE_MAX, `Reference must be ${REFERENCE_MAX} characters or fewer`),
  notes: z.string().max(NOTES_MAX, `Notes must be ${NOTES_MAX} characters or fewer`),
});
export type RequirementFormValues = z.infer<typeof requirementFormSchema>;

export const DEFAULT_REQUIREMENT_FORM_VALUES: RequirementFormValues = {
  crop_id: "",
  variety_id: "",
  required_by_date: "",
  required_quantity: "",
  quantity_uom_id: "",
  reference: "",
  notes: "",
};

export function buildRequirementCreatePayload(
  values: RequirementFormValues,
  clientCommandId: string,
): ProductionRequirementCreate {
  return {
    client_command_id: clientCommandId,
    crop_id: values.crop_id,
    variety_id: values.variety_id || null,
    required_by_date: values.required_by_date,
    required_quantity: values.required_quantity,
    quantity_uom_id: values.quantity_uom_id,
    reference: values.reference.trim() || null,
    notes: values.notes.trim() || null,
  };
}

export const requirementUpdateFormSchema = z.object({
  required_by_date: z.string().min(1, "Required-by date is required"),
  required_quantity: decimalString("Quantity"),
  reference: z.string().max(REFERENCE_MAX, `Reference must be ${REFERENCE_MAX} characters or fewer`),
  notes: z.string().max(NOTES_MAX, `Notes must be ${NOTES_MAX} characters or fewer`),
});
export type RequirementUpdateFormValues = z.infer<typeof requirementUpdateFormSchema>;

export function buildRequirementUpdatePayload(
  values: RequirementUpdateFormValues,
  clientCommandId: string,
): ProductionRequirementUpdate {
  return {
    client_command_id: clientCommandId,
    required_by_date: values.required_by_date,
    required_quantity: values.required_quantity,
    reference: values.reference.trim() || null,
    notes: values.notes.trim() || null,
  };
}

// --- Seeding Program Line -------------------------------------------------------------
// `crop_id` is never a form field -- a plan line always fulfils its parent
// Requirement's own crop (server-enforced); `expected_coverage_uom_id` is
// always the parent Requirement's own quantity UOM, likewise never a
// free choice (see docs/product/OPEN-QUESTIONS.md's "no invented
// conversion" decision).

export const seedingProgramLineFormSchema = z.object({
  variety_id: z.string(),
  planned_sow_date: z.string().min(1, "Planned sow date is required"),
  planned_quantity: decimalString("Planned sowing quantity"),
  planned_quantity_uom_id: z.string().min(1, "Unit is required"),
  expected_coverage_quantity: decimalString("Expected coverage"),
  notes: z.string().max(NOTES_MAX, `Notes must be ${NOTES_MAX} characters or fewer`),
});
export type SeedingProgramLineFormValues = z.infer<typeof seedingProgramLineFormSchema>;

export const DEFAULT_SEEDING_PROGRAM_LINE_FORM_VALUES: SeedingProgramLineFormValues = {
  variety_id: "",
  planned_sow_date: "",
  planned_quantity: "",
  planned_quantity_uom_id: "",
  expected_coverage_quantity: "",
  notes: "",
};

export function buildSeedingProgramLineCreatePayload(
  values: SeedingProgramLineFormValues,
  clientCommandId: string,
  cropId: string,
  expectedCoverageUomId: string,
): SeedingProgramLineCreate {
  return {
    client_command_id: clientCommandId,
    planned_sow_date: values.planned_sow_date,
    crop_id: cropId,
    variety_id: values.variety_id || null,
    planned_quantity: values.planned_quantity,
    planned_quantity_uom_id: values.planned_quantity_uom_id,
    expected_coverage_quantity: values.expected_coverage_quantity,
    expected_coverage_uom_id: expectedCoverageUomId,
    notes: values.notes.trim() || null,
  };
}

export const seedingProgramLineUpdateFormSchema = z.object({
  planned_sow_date: z.string().min(1, "Planned sow date is required"),
  planned_quantity: decimalString("Planned sowing quantity"),
  expected_coverage_quantity: decimalString("Expected coverage"),
  notes: z.string().max(NOTES_MAX, `Notes must be ${NOTES_MAX} characters or fewer`),
});
export type SeedingProgramLineUpdateFormValues = z.infer<typeof seedingProgramLineUpdateFormSchema>;

export function buildSeedingProgramLineUpdatePayload(
  values: SeedingProgramLineUpdateFormValues,
  clientCommandId: string,
): SeedingProgramLineUpdate {
  return {
    client_command_id: clientCommandId,
    planned_sow_date: values.planned_sow_date,
    planned_quantity: values.planned_quantity,
    expected_coverage_quantity: values.expected_coverage_quantity,
    notes: values.notes.trim() || null,
  };
}
