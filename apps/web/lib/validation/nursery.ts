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

const trayEntrySchema = z.object({
  carrier_id: z.string(),
  code: z.string(),
  seeds_sown: z.number({ error: "Seeds sown is required" }).int("Must be a whole number").min(1, "Must be at least 1"),
});

export const sowingFormSchema = z
  .object({
    seeding_station_id: z.string().min(1, "Seeding Station is required"),
    seed_lot_id: z.string().min(1, "Seed Lot is required"),
    seeding_machine_id: z.string(),
    effective_date: z.string().min(1, "Date is required"),
    effective_time_of_day: z.string().min(1, "Time is required"),
    note: z.string(),
    trays: z.array(trayEntrySchema).min(1, "Select at least one Seed Tray"),
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
  effective_date: "",
  effective_time_of_day: "",
  note: "",
  trays: [],
};

export function buildSowingPayload(values: SowingFormValues, clientCommandId: string): SowNewBatchCreate {
  const effectiveTime = new Date(`${values.effective_date}T${values.effective_time_of_day}`).toISOString();
  return {
    client_command_id: clientCommandId,
    seed_lot_id: values.seed_lot_id,
    seeding_station_id: values.seeding_station_id,
    seeding_machine_id: values.seeding_machine_id || null,
    effective_time: effectiveTime,
    note: values.note.trim() || null,
    trays: values.trays.map((t) => ({ carrier_id: t.carrier_id, seeds_sown: t.seeds_sown })),
  };
}

export function totalSeedsSown(trays: { seeds_sown: number }[]): number {
  return trays.reduce((sum, t) => sum + (Number.isFinite(t.seeds_sown) ? t.seeds_sown : 0), 0);
}
