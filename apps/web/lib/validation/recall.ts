import { z } from "zod";

/** PILOT-READY-001: Open/close a Recall Case. Opening requires exactly one
 * scope reference (Crop Batch / Harvested Produce Lot / Graded Produce Lot
 * / Finished Goods Lot) -- mirrors the backend's own exact-one-of rule
 * (`RecallCaseCreate`). Client-side validation is convenience only -- the
 * server remains the sole authority. */

export const RECALL_SCOPE_TYPES = [
  "finished_goods_lot_id",
  "graded_produce_lot_id",
  "harvested_produce_lot_id",
  "crop_batch_id",
] as const;
export type RecallScopeType = (typeof RECALL_SCOPE_TYPES)[number];

export const openRecallCaseFormSchema = z.object({
  code: z.string().min(1, "Recall code is required"),
  effective_date: z.string().min(1, "Date is required"),
  effective_time_of_day: z.string().min(1, "Time is required"),
  scope_type: z.enum(RECALL_SCOPE_TYPES),
  scope_id: z.string().min(1, "Select what this recall applies to"),
  reason_code: z.string().min(1, "Reason code is required"),
  reason_text: z.string().min(1, "Reason is required"),
});

export type OpenRecallCaseFormValues = z.infer<typeof openRecallCaseFormSchema>;

export const closeRecallCaseFormSchema = z.object({
  effective_date: z.string().min(1, "Date is required"),
  effective_time_of_day: z.string().min(1, "Time is required"),
  close_reason: z.string().min(1, "Close reason is required"),
});

export type CloseRecallCaseFormValues = z.infer<typeof closeRecallCaseFormSchema>;
