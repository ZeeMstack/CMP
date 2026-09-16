import { z } from "zod";

import type { SeedLotCreate, SowNewBatchCreate } from "@/lib/api/client";

/** NURSERY-OPS-001: Seed Lot registration -- a traceability source, not a
 * stock-on-hand record (see SEED_SOWING_MODEL.md). Mirrors farmSetup.ts's
 * own plain-`z.number()` + `valueAsNumber: true` convention for numeric
 * inputs, and its two-phase configure/review pattern for the Sowing form. */

const CODE_MAX = 64;

export const seedLotFormSchema = z.object({
  crop_id: z.string().min(1, "Crop is required"),
  variety_id: z.string().min(1, "Variety is required"),
  code: z.string().trim().min(1, "Code is required").max(CODE_MAX, `Code must be ${CODE_MAX} characters or fewer`),
  supplier_name: z.string(),
  supplier_lot_reference: z.string(),
  received_date: z.string(),
  expiry_date: z.string(),
});
export type SeedLotFormValues = z.infer<typeof seedLotFormSchema>;

export const DEFAULT_SEED_LOT_FORM_VALUES: SeedLotFormValues = {
  crop_id: "",
  variety_id: "",
  code: "",
  supplier_name: "",
  supplier_lot_reference: "",
  received_date: "",
  expiry_date: "",
};

export function buildSeedLotPayload(values: SeedLotFormValues): SeedLotCreate {
  return {
    crop_id: values.crop_id,
    variety_id: values.variety_id,
    code: values.code,
    supplier_name: values.supplier_name.trim() || null,
    supplier_lot_reference: values.supplier_lot_reference.trim() || null,
    received_date: values.received_date || null,
    expiry_date: values.expiry_date || null,
  };
}

// --- Sowing -----------------------------------------------------------------

const trayEntrySchema = z
  .object({
    carrier_id: z.string(),
    code: z.string(),
    // CARRIER-CONFIG-001B: known physical capacity for this tray's own
    // CarrierSpecification, or null when the tray is legacy/unspecified --
    // never fabricated, carried only for client-side display/prevalidation.
    biological_position_count: z.number().nullable(),
    sown_site_count: z
      .number({ error: "Sown site count is required" })
      .int("Must be a whole number")
      .min(1, "Must be at least 1"),
    seeds_sown: z.number({ error: "Seeds sown is required" }).int("Must be a whole number").min(1, "Must be at least 1"),
  })
  .refine((t) => t.seeds_sown >= t.sown_site_count, {
    message: "Seeds sown must be greater than or equal to sown site count",
    path: ["seeds_sown"],
  })
  .refine((t) => t.biological_position_count == null || t.sown_site_count <= t.biological_position_count, {
    message: "Sown site count exceeds this tray's known capacity",
    path: ["sown_site_count"],
  });

export const sowingFormSchema = z
  .object({
    seeding_station_id: z.string().min(1, "Seeding Station is required"),
    seed_lot_id: z.string().min(1, "Seed Lot is required"),
    seeding_machine_id: z.string(),
    // HOTFIX (sowing effective-time clock skew): the operator's own
    // deliberate choice to record something other than "now" -- default
    // NOW never carries a client-generated timestamp at all (see
    // `buildSowingPayload`), so `effective_date`/`effective_time_of_day`
    // are only required, and only sent, when this is explicitly true.
    use_custom_time: z.boolean(),
    effective_date: z.string(),
    effective_time_of_day: z.string(),
    note: z.string(),
    trays: z.array(trayEntrySchema).min(1, "Select at least one Seed Tray"),
  })
  .refine((values) => !values.use_custom_time || values.effective_date.length > 0, {
    message: "Date is required",
    path: ["effective_date"],
  })
  .refine((values) => !values.use_custom_time || values.effective_time_of_day.length > 0, {
    message: "Time is required",
    path: ["effective_time_of_day"],
  })
  .refine(
    (values) => {
      const ids = values.trays.map((t) => t.carrier_id);
      return ids.length === new Set(ids).size;
    },
    { message: "Each Seed Tray may only be selected once", path: ["trays"] },
  );
export type SowingFormValues = z.infer<typeof sowingFormSchema>;

export const DEFAULT_SOWING_FORM_VALUES: SowingFormValues = {
  seeding_station_id: "",
  seed_lot_id: "",
  seeding_machine_id: "",
  use_custom_time: false,
  effective_date: "",
  effective_time_of_day: "",
  note: "",
  trays: [],
};

export function buildSowingPayload(
  values: SowingFormValues,
  clientCommandId: string,
  seedingProgramLineId?: string | null,
): SowNewBatchCreate {
  // HOTFIX (sowing effective-time clock skew): default "Sow now" omits
  // `effective_time` entirely rather than sending a browser-clock-derived
  // timestamp -- the server assigns its own authoritative current time
  // (`nursery_service.sow_new_batch`), which can never race ahead of
  // itself the way an operator's local clock occasionally does. Only an
  // operator's own explicit date/time selection is ever sent as a
  // concrete instant, and the server still rejects that if it is
  // genuinely in the future.
  const effectiveTime = values.use_custom_time
    ? new Date(`${values.effective_date}T${values.effective_time_of_day}`).toISOString()
    : null;
  return {
    client_command_id: clientCommandId,
    seed_lot_id: values.seed_lot_id,
    seeding_station_id: values.seeding_station_id,
    seeding_machine_id: values.seeding_machine_id || null,
    effective_time: effectiveTime,
    note: values.note.trim() || null,
    trays: values.trays.map((t) => ({
      carrier_id: t.carrier_id,
      sown_site_count: t.sown_site_count,
      seeds_sown: t.seeds_sown,
    })),
    // PLANNING-OPS-001: optional Seeding Program Line hand-off from
    // "Sow Now" -- never required, an ordinary ad-hoc Sowing omits it.
    seeding_program_line_id: seedingProgramLineId || null,
  };
}

export function totalSeedsSown(trays: { seeds_sown: number }[]): number {
  return trays.reduce((sum, t) => sum + (Number.isFinite(t.seeds_sown) ? t.seeds_sown : 0), 0);
}

export function totalSownSiteCount(trays: { sown_site_count: number }[]): number {
  return trays.reduce((sum, t) => sum + (Number.isFinite(t.sown_site_count) ? t.sown_site_count : 0), 0);
}
