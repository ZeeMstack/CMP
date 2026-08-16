import { z } from "zod";

import type { CorrectSeedlingDispositionCreate, RecordSeedlingDispositionCreate } from "@/lib/api/client";

/** NURSERY-OPS-003B: Seedling Biological Dispositions. The operator supplies
 * only the positive count of seedlings that stopped continuing (never a
 * signed delta, never a recount of the whole remaining population -- section
 * 0.2), a reason, and when it happened. The backend always recomputes the
 * resulting balance authoritatively; this schema only shapes the command
 * payload, never a client-trusted preview value. Mirrors seedlingEntry.ts's
 * two-phase configure/review pattern and date+time-of-day convention. */

const OTHER_REASON_CODE = "OTHER";

export const recordDispositionFormSchema = z
  .object({
    batch_carrier_assignment_id: z.string().min(1, "Seed Tray is required"),
    quantity: z
      .string()
      .min(1, "Quantity is required")
      .refine((v) => Number.isInteger(Number(v)) && Number(v) > 0, "Quantity must be a whole number greater than 0"),
    reason_code: z.string().min(1, "Reason is required"),
    effective_date: z.string().min(1, "Date is required"),
    effective_time_of_day: z.string().min(1, "Time is required"),
    note: z.string(),
  })
  .superRefine((values, ctx) => {
    if (values.reason_code === OTHER_REASON_CODE && values.note.trim().length === 0) {
      ctx.addIssue({ code: z.ZodIssueCode.custom, path: ["note"], message: "A note is required when reason is Other" });
    }
  });
export type RecordDispositionFormValues = z.infer<typeof recordDispositionFormSchema>;

export const DEFAULT_RECORD_DISPOSITION_FORM_VALUES: RecordDispositionFormValues = {
  batch_carrier_assignment_id: "",
  quantity: "",
  reason_code: "",
  effective_date: "",
  effective_time_of_day: "",
  note: "",
};

export function buildRecordDispositionPayload(
  values: RecordDispositionFormValues,
  clientCommandId: string,
): RecordSeedlingDispositionCreate {
  return {
    client_command_id: clientCommandId,
    batch_carrier_assignment_id: values.batch_carrier_assignment_id,
    quantity: Number(values.quantity),
    reason_code: values.reason_code,
    effective_time: new Date(`${values.effective_date}T${values.effective_time_of_day}`).toISOString(),
    note: values.note.trim() || null,
  };
}

/** Section 0.B/18: `corrected: null` means VOID (reversal only, no
 * replacement); a populated `corrected` means replace the original with a
 * corrected biological fact. One form, one backend command either way. */
export const correctDispositionFormSchema = z
  .object({
    mode: z.enum(["void", "replace"]),
    quantity: z.string(),
    reason_code: z.string(),
    effective_date: z.string(),
    effective_time_of_day: z.string(),
    note: z.string(),
  })
  .superRefine((values, ctx) => {
    if (values.mode !== "replace") return;
    if (values.quantity.length === 0 || !(Number.isInteger(Number(values.quantity)) && Number(values.quantity) > 0)) {
      ctx.addIssue({ code: z.ZodIssueCode.custom, path: ["quantity"], message: "Quantity must be a whole number greater than 0" });
    }
    if (values.reason_code.length === 0) {
      ctx.addIssue({ code: z.ZodIssueCode.custom, path: ["reason_code"], message: "Reason is required" });
    }
    if (values.effective_date.length === 0) {
      ctx.addIssue({ code: z.ZodIssueCode.custom, path: ["effective_date"], message: "Date is required" });
    }
    if (values.effective_time_of_day.length === 0) {
      ctx.addIssue({ code: z.ZodIssueCode.custom, path: ["effective_time_of_day"], message: "Time is required" });
    }
    if (values.reason_code === OTHER_REASON_CODE && values.note.trim().length === 0) {
      ctx.addIssue({ code: z.ZodIssueCode.custom, path: ["note"], message: "A note is required when reason is Other" });
    }
  });
export type CorrectDispositionFormValues = z.infer<typeof correctDispositionFormSchema>;

export const DEFAULT_CORRECT_DISPOSITION_FORM_VALUES: CorrectDispositionFormValues = {
  mode: "void",
  quantity: "",
  reason_code: "",
  effective_date: "",
  effective_time_of_day: "",
  note: "",
};

export function buildCorrectDispositionPayload(
  values: CorrectDispositionFormValues,
  clientCommandId: string,
): CorrectSeedlingDispositionCreate {
  if (values.mode === "void") {
    return { client_command_id: clientCommandId, corrected: null };
  }
  return {
    client_command_id: clientCommandId,
    corrected: {
      quantity: Number(values.quantity),
      reason_code: values.reason_code,
      effective_time: new Date(`${values.effective_date}T${values.effective_time_of_day}`).toISOString(),
      note: values.note.trim() || null,
    },
  };
}
