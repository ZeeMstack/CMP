import { z } from "zod";

import type { GreenhouseSetupCreate } from "@/lib/api/client";

/**
 * FARM-SETUP-001: deliberately flat, "operator-friendly" form input --
 * the user thinks in "how many Zones / Spans per Zone / Tables per Span",
 * not in a hand-built array of per-Zone/per-Span objects (that generic
 * graph-builder UI is explicitly out of scope, see CLAUDE.md "Keep the
 * first experience practical"). `buildGreenhouseSetupPayload` below
 * expands these uniform counts into the backend's real nested,
 * classification-specific request shape (one generator config per Span,
 * matching `TableGeneratorConfig`/`GutterGeneratorConfig` exactly) --
 * every Zone/Span gets the SAME generator, replicated, which is also
 * exactly why table codes naturally restart per Span (each Span's own
 * generator always starts at 1).
 */

const CODE_MAX = 32;
const PREFIX_MAX = 12;
// Browser/UI safety ceiling only -- never confused with the backend's own
// authoritative MAX_BULK_CHILDREN/MAX_BULK_POSITIONS limits, which remain
// independently enforced server-side regardless of what this allows.
const MAX_COUNT = 50;

const codeSchema = z
  .string()
  .trim()
  .min(1, "Code is required")
  .max(CODE_MAX, `Code must be ${CODE_MAX} characters or fewer`);

const prefixSchema = z
  .string()
  .trim()
  .min(1, "Prefix is required")
  .max(PREFIX_MAX, `Prefix must be ${PREFIX_MAX} characters or fewer`);

// Plain z.number() (not z.coerce.number()) -- form inputs convert the raw
// string to a number themselves via RHF's `valueAsNumber: true` on every
// numeric <input>, so the schema's input and output types stay identical
// (coercion schemas make them diverge, which the zodResolver's generic
// signature cannot reconcile with react-hook-form's own field typing).
const positiveCount = (max: number, label: string) =>
  z
    .number({ error: `${label} is required` })
    .int(`${label} must be a whole number`)
    .min(1, `${label} must be at least 1`)
    .max(max, `${label} must be ${max} or fewer`);

const positiveCapacity = z
  .number({ error: "Capacity is required" })
  .int("Capacity must be a whole number")
  .min(1, "Capacity must be at least 1")
  .max(100000, "Capacity is unrealistically large");

export const leafyFormSchema = z.object({
  zoneCount: positiveCount(MAX_COUNT, "Number of zones"),
  zoneCodePrefix: prefixSchema,
  spansPerZone: positiveCount(MAX_COUNT, "Spans per zone"),
  spanCodePrefix: prefixSchema,
  tablesPerSpan: positiveCount(500, "Tables per span"),
  tableCodePrefix: prefixSchema,
  tableCapacity: positiveCapacity,
});
export type LeafyFormValues = z.infer<typeof leafyFormSchema>;

export const vinesFormSchema = z.object({
  zoneCount: positiveCount(MAX_COUNT, "Number of zones"),
  zoneCodePrefix: prefixSchema,
  spansPerZone: positiveCount(MAX_COUNT, "Spans per zone"),
  spanCodePrefix: prefixSchema,
  guttersPerSpan: positiveCount(500, "Gutters per span"),
  gutterCodePrefix: prefixSchema,
  continueGutterNumbering: z.boolean(),
  bagPositionsPerGutter: positiveCount(500, "Grow bag positions per gutter"),
  bagPositionCodePrefix: prefixSchema,
});
export type VinesFormValues = z.infer<typeof vinesFormSchema>;

// `code` is plain (unvalidated) here -- an unselected trolley/seeding
// machine still has to satisfy this sub-schema's own type shape even
// though its fields are meaningless while hidden, so requiring a non-blank
// code unconditionally would make the DEFAULT, nothing-selected form state
// itself invalid. The real "is a code required" check lives in
// `greenhouseSetupFormSchema`'s `.refine()` below, applied ONLY when
// `includeTrolley`/`includeSeedingMachine` is true.
const trolleyFormSchema = z.object({
  code: z.string(),
  levelCount: positiveCount(20, "Number of levels"),
  traysPerLevel: positiveCount(200, "Trays per level"),
});

const seedingMachineFormSchema = z.object({
  code: z.string(),
});

// FARM-SETUP-001.1: like `trolleyFormSchema`/`seedingMachineFormSchema`
// above, `code` stays unvalidated here -- required-when-included is
// enforced by `greenhouseSetupFormSchema`'s own `.refine()` below.
const nurserySectionFormSchema = z.object({
  code: z.string(),
  name: z.string(),
});

export const nurseryFormSchema = z.object({
  includeSeedingStation: z.boolean(),
  seedingStation: nurserySectionFormSchema,
  includeGerminationChamber: z.boolean(),
  germinationChamber: nurserySectionFormSchema,
  includeSeedling: z.boolean(),
  seedlingTableCount: positiveCount(500, "Number of seedling tables"),
  seedlingCapacity: positiveCapacity,
  includeIntersalads: z.boolean(),
  intersaladsTableCount: positiveCount(500, "Number of InterSalads tables"),
  intersaladsCapacity: positiveCapacity,
  includeIntervines: z.boolean(),
  intervinesTableCount: positiveCount(500, "Number of InterVines tables"),
  intervinesCapacity: positiveCapacity,
  includeTrolley: z.boolean(),
  trolley: trolleyFormSchema,
  includeSeedingMachine: z.boolean(),
  seedingMachine: seedingMachineFormSchema,
});
export type NurseryFormValues = z.infer<typeof nurseryFormSchema>;

export const greenhouseSetupFormSchema = z
  .object({
    code: codeSchema,
    name: z.string().trim().min(1, "Name is required").max(120, "Name must be 120 characters or fewer"),
    classification: z.enum(["nursery", "leafy_greens", "vines"]),
    leafy: leafyFormSchema,
    vines: vinesFormSchema,
    nursery: nurseryFormSchema,
  })
  .refine(
    (values) => {
      if (values.classification !== "nursery") return true;
      const n = values.nursery;
      return (
        n.includeSeedingStation || n.includeGerminationChamber ||
        n.includeSeedling || n.includeIntersalads || n.includeIntervines ||
        n.includeTrolley || n.includeSeedingMachine
      );
    },
    {
      message: "Configure at least one Nursery section (seeding station, germination chamber, tables, trolley, or seeding machine)",
      path: ["nursery"],
    },
  )
  .refine(
    (values) =>
      values.classification !== "nursery" || !values.nursery.includeSeedingStation || values.nursery.seedingStation.code.trim().length > 0,
    { message: "Seeding station code is required", path: ["nursery", "seedingStation", "code"] },
  )
  .refine(
    (values) =>
      values.classification !== "nursery" || !values.nursery.includeGerminationChamber || values.nursery.germinationChamber.code.trim().length > 0,
    { message: "Germination chamber code is required", path: ["nursery", "germinationChamber", "code"] },
  )
  .refine((values) => values.classification !== "nursery" || !values.nursery.includeTrolley || values.nursery.trolley.code.trim().length > 0, {
    message: "Trolley code is required",
    path: ["nursery", "trolley", "code"],
  })
  .refine(
    (values) =>
      values.classification !== "nursery" || !values.nursery.includeSeedingMachine || values.nursery.seedingMachine.code.trim().length > 0,
    { message: "Seeding machine code is required", path: ["nursery", "seedingMachine", "code"] },
  );
export type GreenhouseSetupFormValues = z.infer<typeof greenhouseSetupFormSchema>;

export const DEFAULT_FORM_VALUES: GreenhouseSetupFormValues = {
  code: "",
  name: "",
  classification: "leafy_greens",
  leafy: {
    zoneCount: 1,
    zoneCodePrefix: "Z",
    spansPerZone: 1,
    spanCodePrefix: "S",
    tablesPerSpan: 1,
    tableCodePrefix: "T",
    tableCapacity: 1,
  },
  vines: {
    zoneCount: 1,
    zoneCodePrefix: "Z",
    spansPerZone: 1,
    spanCodePrefix: "S",
    guttersPerSpan: 1,
    gutterCodePrefix: "G",
    continueGutterNumbering: false,
    bagPositionsPerGutter: 1,
    bagPositionCodePrefix: "BP",
  },
  nursery: {
    includeSeedingStation: false,
    seedingStation: { code: "", name: "" },
    includeGerminationChamber: false,
    germinationChamber: { code: "", name: "" },
    includeSeedling: true,
    seedlingTableCount: 1,
    seedlingCapacity: 1,
    includeIntersalads: false,
    intersaladsTableCount: 1,
    intersaladsCapacity: 1,
    includeIntervines: false,
    intervinesTableCount: 1,
    intervinesCapacity: 1,
    includeTrolley: false,
    trolley: { code: "", levelCount: 1, traysPerLevel: 1 },
    includeSeedingMachine: false,
    seedingMachine: { code: "" },
  },
};

const pad2 = (n: number) => String(n).padStart(2, "0");

/** Expands the flat, uniform form input into the backend's real nested
 * setup request -- every Zone gets the same N Spans, every Span gets the
 * same table/gutter generator (server-generated codes, never
 * client-invented UUID-shaped identifiers). */
export function buildGreenhouseSetupPayload(values: GreenhouseSetupFormValues, clientCommandId: string): GreenhouseSetupCreate {
  const base = { code: values.code, name: values.name, classification: values.classification, client_command_id: clientCommandId };

  if (values.classification === "leafy_greens") {
    const { zoneCount, zoneCodePrefix, spansPerZone, spanCodePrefix, tablesPerSpan, tableCodePrefix, tableCapacity } = values.leafy;
    return {
      ...base,
      leafy: {
        zones: Array.from({ length: zoneCount }, (_, z) => ({
          code: `${zoneCodePrefix}${pad2(z + 1)}`,
          spans: Array.from({ length: spansPerZone }, (_, s) => ({
            code: `${spanCodePrefix}${pad2(s + 1)}`,
            tables: {
              code_prefix: tableCodePrefix, start: 1, end: tablesPerSpan, pad_width: 2, capacity: tableCapacity,
            },
          })),
        })),
      },
    };
  }

  if (values.classification === "vines") {
    const {
      zoneCount, zoneCodePrefix, spansPerZone, spanCodePrefix, guttersPerSpan, gutterCodePrefix,
      continueGutterNumbering, bagPositionsPerGutter, bagPositionCodePrefix,
    } = values.vines;
    return {
      ...base,
      vines: {
        zones: Array.from({ length: zoneCount }, (_, z) => ({
          code: `${zoneCodePrefix}${pad2(z + 1)}`,
          spans: Array.from({ length: spansPerZone }, (_, s) => {
            const spanIndex = z * spansPerZone + s; // 0-based, across the whole greenhouse
            const start = continueGutterNumbering ? spanIndex * guttersPerSpan + 1 : 1;
            const end = start + guttersPerSpan - 1;
            return {
              code: `${spanCodePrefix}${pad2(s + 1)}`,
              gutters: {
                code_prefix: gutterCodePrefix, start, end, pad_width: 2,
                bag_positions_per_gutter: bagPositionsPerGutter, bag_position_code_prefix: bagPositionCodePrefix,
                bag_position_pad_width: 3,
              },
            };
          }),
        })),
      },
    };
  }

  const n = values.nursery;
  return {
    ...base,
    nursery: {
      seeding_station: n.includeSeedingStation
        ? { code: n.seedingStation.code, name: n.seedingStation.name.trim() ? n.seedingStation.name : null }
        : null,
      germination_chamber: n.includeGerminationChamber
        ? { code: n.germinationChamber.code, name: n.germinationChamber.name.trim() ? n.germinationChamber.name : null }
        : null,
      seedling_tables: n.includeSeedling
        ? { code_prefix: "ST", start: 1, end: n.seedlingTableCount, pad_width: 2, capacity: n.seedlingCapacity }
        : null,
      intersalads_tables: n.includeIntersalads
        ? { code_prefix: "IS", start: 1, end: n.intersaladsTableCount, pad_width: 2, capacity: n.intersaladsCapacity }
        : null,
      intervines_tables: n.includeIntervines
        ? { code_prefix: "IV", start: 1, end: n.intervinesTableCount, pad_width: 2, capacity: n.intervinesCapacity }
        : null,
      trolleys: n.includeTrolley
        ? [
            {
              code: n.trolley.code,
              name: null,
              levels: {
                shelf_count: n.trolley.levelCount, slots_per_shelf: n.trolley.traysPerLevel,
                shelf_prefix: "SH-", slot_prefix: "SL-", shelf_pad_width: 2, slot_pad_width: 2, slot_capacity: null,
              },
            },
          ]
        : [],
      seeding_machines: n.includeSeedingMachine ? [{ code: n.seedingMachine.code, name: null }] : [],
    },
  };
}
