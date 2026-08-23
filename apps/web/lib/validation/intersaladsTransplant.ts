import { z } from "zod";

import type { IntersaladsTransplantCreate } from "@/lib/api/client";

/** NURSERY-OPS-004B.2: InterSalads Transplant -- Seedling source Tray(s) to
 * Nursery Cultivation Plate(s) on InterSalads Table(s), one atomic composite
 * command. Section 6 (frozen): destination-centric UX, never a raw N×M
 * allocation matrix -- each destination card carries its own list of
 * `{source_assignment_id, quantity}` allocations, and `assigned_plant_count`
 * is always DERIVED (sum of that destination's own allocations), never a
 * second, independently-typed number that could disagree with them.
 *
 * All cross-referencing checks (per-source over-allocation including
 * transplant-boundary losses, per-destination capacity, duplicate Plate)
 * live in one top-level `superRefine` here so the exact same arithmetic
 * backs both the blocking validation and the review-screen preview -- never
 * two independently-maintained copies of the same math (section 9/12/23). */

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
  tray_code: z.string(),
  // Authoritative `current_source_available_count` at the moment this
  // source was added to the draft -- display/prevalidation only, never
  // trusted as the final word (section 8/9: backend recalculates
  // authoritatively at submit).
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
  destination_carrier_id: z.string().min(1, "Plate is required"),
  plate_code: z.string(),
  biological_position_count: z.number().nullable(),
  destination_location_id: z.string().min(1, "InterSalads Table is required"),
  table_code: z.string(),
  note: z.string(),
  allocations: z.array(allocationEntrySchema).min(1, "Add at least one source allocation"),
});
export type DestinationEntryValues = z.infer<typeof destinationEntrySchema>;

export const intersaladsTransplantFormSchema = z
  .object({
    batch_id: z.string(),
    batch_code: z.string(),
    crop_common_name: z.string(),
    variety_name: z.string(),
    sources: z.array(sourceEntrySchema).min(1, "Select at least one source Tray"),
    destinations: z.array(destinationEntrySchema).min(1, "Add at least one destination Plate"),
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
          message: "Allocated quantity plus losses exceeds this source's available seedlings",
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
export type IntersaladsTransplantFormValues = z.infer<typeof intersaladsTransplantFormSchema>;

export const DEFAULT_INTERSALADS_TRANSPLANT_FORM_VALUES: IntersaladsTransplantFormValues = {
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

/** Section 12: destination `assigned_plant_count` is always the sum of its
 * own allocations -- never a second, separately-typed number the operator
 * could type in disagreement with them. */
export function destinationAssignedCount(destination: { allocations: { quantity: number }[] }): number {
  return destination.allocations.reduce((sum, a) => sum + (Number.isFinite(a.quantity) ? a.quantity : 0), 0);
}

/** Section 9: total allocated FROM one source, across every destination in
 * the current draft (a source may feed more than one destination). */
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

/** Section 9 (frozen preview formula):
 * remaining = current_source_available_count - allocated - losses. */
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

export function buildIntersaladsTransplantPayload(
  values: IntersaladsTransplantFormValues,
  clientCommandId: string,
): IntersaladsTransplantCreate {
  const effectiveTime = new Date(`${values.effective_date}T${values.effective_time_of_day}`).toISOString();
  const allocations: IntersaladsTransplantCreate["allocations"] = [];
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
