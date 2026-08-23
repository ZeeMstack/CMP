import { z } from "zod";

import type { LeafyProductionTransferCreate } from "@/lib/api/client";

/** NURSERY-OPS-005B: Leafy Production Transfer -- Nursery Cultivation
 * Plate source(s) to Production Cultivation Plate(s) placed on Leafy
 * Greenhouse -> Zone -> Span -> Table, one atomic composite command.
 * Mirrors `lib/validation/intersaladsTransplant.ts`'s exact destination-
 * centric shape and arithmetic (never a raw N×M allocation matrix; every
 * cross-referencing check lives in one top-level `superRefine` so the same
 * math backs both blocking validation and the review-screen preview) --
 * the one structural difference is each destination card additionally
 * carries the Leafy ancestry ids (`leafy_greenhouse_id`/`zone_id`/
 * `span_id`) needed for the cascading picker's own UX state; only
 * `destination_location_id` (the Table itself) is ever sent to the
 * backend (section 7 of the ticket: Greenhouse/Zone/Span are frontend-only
 * state, never write-authoritative identifiers). */

const OTHER_LOSS_REQUIRES_NOTE = "A note is required when there is a loss in this category";

const allocationEntrySchema = z.object({
  source_assignment_id: z.string().min(1),
  quantity: z
    .number({ error: "Quantity is required" })
    .int("Must be a whole number")
    .positive("Must be greater than 0"),
});
export type AllocationEntryValues = z.infer<typeof allocationEntrySchema>;

export const sourceEntrySchema = z.object({
  source_assignment_id: z.string().min(1),
  plate_code: z.string(),
  // Authoritative `authoritative_available_count` at the moment this
  // source was added to the draft -- display/prevalidation only, never
  // trusted as the final word (backend recalculates authoritatively at
  // submit, via transplant_source_authority -- never a client-side sum).
  current_available: z.number(),
  transplant_damage_count: z.number().int().min(0),
  qc_rejection_count: z.number().int().min(0),
  sample_count: z.number().int().min(0),
  other_loss_count: z.number().int().min(0),
  other_loss_note: z.string(),
  note: z.string(),
});
export type SourceEntryValues = z.infer<typeof sourceEntrySchema>;

export const destinationEntrySchema = z.object({
  destination_carrier_id: z.string().min(1, "Production Plate is required"),
  plate_code: z.string(),
  biological_position_count: z.number().nullable(),
  leafy_greenhouse_id: z.string().min(1, "Greenhouse is required"),
  zone_id: z.string().min(1, "Zone is required"),
  span_id: z.string().min(1, "Span is required"),
  destination_location_id: z.string().min(1, "Table is required"),
  table_label: z.string(),
  // Derived from the selected Table (never separately editable, never sent
  // to the backend -- see `buildLeafyProductionTransferPayload`); repository
  // convention: NULL means "not configured", effective capacity 1.
  table_capacity: z.number().nullable(),
  note: z.string(),
  allocations: z.array(allocationEntrySchema).min(1, "Add at least one source allocation"),
});
export type DestinationEntryValues = z.infer<typeof destinationEntrySchema>;

export const leafyProductionTransferFormSchema = z
  .object({
    batch_id: z.string(),
    batch_code: z.string(),
    crop_common_name: z.string(),
    variety_name: z.string(),
    sources: z.array(sourceEntrySchema).min(1, "Select at least one source Nursery Plate"),
    destinations: z.array(destinationEntrySchema).min(1, "Add at least one destination Production Plate"),
    effective_date: z.string().min(1, "Date is required"),
    effective_time_of_day: z.string().min(1, "Time is required"),
    note: z.string(),
  })
  .superRefine((values, ctx) => {
    values.sources.forEach((source, index) => {
      if (source.other_loss_count > 0 && source.other_loss_note.trim().length === 0) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: ["sources", index, "other_loss_note"],
          message: OTHER_LOSS_REQUIRES_NOTE,
        });
      }
      const remaining = sourceRemaining(values, source.source_assignment_id);
      if (remaining < 0) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: ["sources", index, "current_available"],
          message: "Allocated quantity plus losses exceeds this source's available population",
        });
      }
    });

    const seenPlateIds = new Set<string>();
    values.destinations.forEach((destination, index) => {
      if (seenPlateIds.has(destination.destination_carrier_id)) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: ["destinations", index, "destination_carrier_id"],
          message: "This Plate is already used as another destination in this transaction",
        });
      }
      seenPlateIds.add(destination.destination_carrier_id);

      const assigned = destinationAssignedCount(destination);
      if (destination.biological_position_count != null && assigned > destination.biological_position_count) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: ["destinations", index, "allocations"],
          message: `Assigned count (${assigned}) exceeds this Plate's capacity (${destination.biological_position_count})`,
        });
      }

      const sourceIds = new Set(values.sources.map((s) => s.source_assignment_id));
      destination.allocations.forEach((allocation, allocationIndex) => {
        if (!sourceIds.has(allocation.source_assignment_id)) {
          ctx.addIssue({
            code: z.ZodIssueCode.custom,
            path: ["destinations", index, "allocations", allocationIndex, "source_assignment_id"],
            message: "This source is no longer part of the transaction",
          });
        }
      });
    });
  });
export type LeafyProductionTransferFormValues = z.infer<typeof leafyProductionTransferFormSchema>;

export const DEFAULT_LEAFY_PRODUCTION_TRANSFER_FORM_VALUES: LeafyProductionTransferFormValues = {
  batch_id: "",
  batch_code: "",
  crop_common_name: "",
  variety_name: "",
  sources: [],
  destinations: [],
  effective_date: "",
  effective_time_of_day: "",
  note: "",
};

export function destinationAssignedCount(destination: { allocations: { quantity: number }[] }): number {
  return destination.allocations.reduce((sum, a) => sum + (Number.isFinite(a.quantity) ? a.quantity : 0), 0);
}

export function sourceAllocatedTotal(
  values: { destinations: { allocations: { source_assignment_id: string; quantity: number }[] }[] },
  sourceAssignmentId: string,
): number {
  let total = 0;
  for (const destination of values.destinations) {
    for (const allocation of destination.allocations) {
      if (allocation.source_assignment_id === sourceAssignmentId && Number.isFinite(allocation.quantity)) {
        total += allocation.quantity;
      }
    }
  }
  return total;
}

export function sourceRemaining(
  values: {
    sources: {
      source_assignment_id: string;
      current_available: number;
      transplant_damage_count: number;
      qc_rejection_count: number;
      sample_count: number;
      other_loss_count: number;
    }[];
    destinations: { allocations: { source_assignment_id: string; quantity: number }[] }[];
  },
  sourceAssignmentId: string,
): number {
  const source = values.sources.find((s) => s.source_assignment_id === sourceAssignmentId);
  if (!source) return 0;
  const allocated = sourceAllocatedTotal(values, sourceAssignmentId);
  const losses =
    source.transplant_damage_count + source.qc_rejection_count + source.sample_count + source.other_loss_count;
  return source.current_available - allocated - losses;
}

export function totalTransplantedCount(values: { destinations: { allocations: { quantity: number }[] }[] }): number {
  return values.destinations.reduce((sum, d) => sum + destinationAssignedCount(d), 0);
}

export function totalLossCount(values: {
  sources: {
    transplant_damage_count: number;
    qc_rejection_count: number;
    sample_count: number;
    other_loss_count: number;
  }[];
}): number {
  return values.sources.reduce(
    (sum, s) => sum + s.transplant_damage_count + s.qc_rejection_count + s.sample_count + s.other_loss_count,
    0,
  );
}

export function buildLeafyProductionTransferPayload(
  values: LeafyProductionTransferFormValues,
  clientCommandId: string,
): LeafyProductionTransferCreate {
  const effectiveTime = new Date(`${values.effective_date}T${values.effective_time_of_day}`).toISOString();
  const allocations: LeafyProductionTransferCreate["allocations"] = [];
  for (const destination of values.destinations) {
    for (const allocation of destination.allocations) {
      allocations.push({
        source_assignment_id: allocation.source_assignment_id,
        destination_carrier_id: destination.destination_carrier_id,
        allocated_plant_count: allocation.quantity,
      });
    }
  }
  return {
    client_command_id: clientCommandId,
    effective_time: effectiveTime,
    note: values.note.trim() || null,
    source_lines: values.sources.map((s) => ({
      source_assignment_id: s.source_assignment_id,
      transplant_damage_count: s.transplant_damage_count,
      qc_rejection_count: s.qc_rejection_count,
      sample_count: s.sample_count,
      other_loss_count: s.other_loss_count,
      other_loss_note: s.other_loss_note.trim() || null,
      note: s.note.trim() || null,
    })),
    destination_lines: values.destinations.map((d) => ({
      destination_carrier_id: d.destination_carrier_id,
      assigned_plant_count: destinationAssignedCount(d),
      destination_location_id: d.destination_location_id,
      note: d.note.trim() || null,
    })),
    allocations,
  };
}
