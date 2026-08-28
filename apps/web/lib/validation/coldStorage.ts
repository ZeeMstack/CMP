import { z } from "zod";

/** PILOT-READY-001: Record a Finished Goods Storage movement (place a lot
 * into Cold Storage, release it back out, or transfer it between
 * locations) -- mirrors the backend's own kind-specific shape exactly
 * (`FinishedGoodsStorageMovementCreate`): `place` requires only a
 * destination, `release` requires only a source, `transfer` requires both
 * and they must differ. Client-side validation is convenience only -- the
 * server remains the sole authority. */

export const MOVEMENT_KINDS = ["place", "transfer", "release"] as const;
export type MovementKind = (typeof MOVEMENT_KINDS)[number];

export const recordStorageMovementFormSchema = z
  .object({
    finished_goods_lot_id: z.string().min(1, "Select a Finished Goods Lot"),
    movement_kind: z.enum(MOVEMENT_KINDS),
    source_location_id: z.string(),
    destination_location_id: z.string(),
    moved_weight_kg: z.number({ error: "Weight is required" }).positive("Must be greater than 0"),
    moved_package_count: z.number({ error: "Package count is required" }).int().positive("Must be greater than 0"),
    effective_date: z.string().min(1, "Date is required"),
    effective_time_of_day: z.string().min(1, "Time is required"),
    note: z.string(),
  })
  .superRefine((values, ctx) => {
    if (values.movement_kind === "place") {
      if (!values.destination_location_id) {
        ctx.addIssue({ code: z.ZodIssueCode.custom, path: ["destination_location_id"], message: "Destination is required" });
      }
    } else if (values.movement_kind === "release") {
      if (!values.source_location_id) {
        ctx.addIssue({ code: z.ZodIssueCode.custom, path: ["source_location_id"], message: "Source is required" });
      }
    } else {
      if (!values.source_location_id) {
        ctx.addIssue({ code: z.ZodIssueCode.custom, path: ["source_location_id"], message: "Source is required" });
      }
      if (!values.destination_location_id) {
        ctx.addIssue({ code: z.ZodIssueCode.custom, path: ["destination_location_id"], message: "Destination is required" });
      }
      if (
        values.source_location_id && values.destination_location_id
        && values.source_location_id === values.destination_location_id
      ) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom, path: ["destination_location_id"], message: "Source and destination must differ",
        });
      }
    }
  });

export type RecordStorageMovementFormValues = z.infer<typeof recordStorageMovementFormSchema>;
