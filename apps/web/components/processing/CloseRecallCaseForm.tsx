"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { useForm } from "react-hook-form";

import { Button } from "@/components/ui/Button";
import type { RecallCaseClose } from "@/lib/api/client";
import { AppError, friendlyMutationErrorMessage } from "@/lib/errors/adapter";
import { closeRecallCaseFormSchema, type CloseRecallCaseFormValues } from "@/lib/validation/recall";

const inputClass =
  "min-h-11 w-full rounded-md border border-border-subtle bg-surface px-3 text-sm text-ink focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-600";
const labelClass = "block text-sm font-medium text-ink";
const errorClass = "text-xs text-red-700";

function Field({ label, error, children }: { label: string; error?: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1">
      <span className={labelClass}>{label}</span>
      {children}
      {error && <span className={errorClass}>{error}</span>}
    </label>
  );
}

function nowDateAndTime() {
  const now = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  return {
    date: `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`,
    time: `${pad(now.getHours())}:${pad(now.getMinutes())}`,
  };
}

/** PILOT-READY-001: "Close Recall Case" -- a closed case is a terminal,
 * append-only fact (mirrors every other command in this app: no
 * un-close). Shown only when the case is still open. */
export function CloseRecallCaseForm({
  onSubmit,
  isSubmitting,
  serverError,
}: {
  onSubmit: (payload: RecallCaseClose) => void;
  isSubmitting: boolean;
  serverError?: AppError | null;
}) {
  const [clientCommandId] = useState(() => crypto.randomUUID());
  const initial = nowDateAndTime();

  const {
    register, handleSubmit, formState: { errors },
  } = useForm<CloseRecallCaseFormValues>({
    resolver: zodResolver(closeRecallCaseFormSchema),
    defaultValues: { effective_date: initial.date, effective_time_of_day: initial.time, close_reason: "" },
    mode: "onBlur",
  });

  function submit(values: CloseRecallCaseFormValues) {
    const effectiveTime = new Date(`${values.effective_date}T${values.effective_time_of_day}`).toISOString();
    const payload: RecallCaseClose = {
      client_command_id: clientCommandId,
      effective_time: effectiveTime,
      close_reason: values.close_reason.trim(),
    };
    onSubmit(payload);
  }

  return (
    <form
      onSubmit={handleSubmit(submit)}
      className="flex flex-col gap-3 rounded-xl border border-border-subtle bg-surface p-4"
    >
      <h2 className="font-serif text-base font-semibold text-ink">Close Recall Case</h2>
      <Field label="Close reason" error={errors.close_reason?.message}>
        <textarea className={`${inputClass} min-h-20`} rows={2} {...register("close_reason")} />
      </Field>
      <fieldset className="grid grid-cols-2 gap-3">
        <Field label="Date" error={errors.effective_date?.message}>
          <input type="date" className={inputClass} {...register("effective_date")} />
        </Field>
        <Field label="Time" error={errors.effective_time_of_day?.message}>
          <input type="time" className={inputClass} {...register("effective_time_of_day")} />
        </Field>
      </fieldset>
      {serverError && (
        <p role="alert" className={errorClass}>
          {friendlyMutationErrorMessage(serverError)}
        </p>
      )}
      <div>
        <Button type="submit" variant="primary" disabled={isSubmitting}>
          {isSubmitting ? "Closing…" : "Close Recall Case"}
        </Button>
      </div>
    </form>
  );
}
