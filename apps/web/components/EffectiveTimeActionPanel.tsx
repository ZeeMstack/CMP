"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import type { ReactNode } from "react";
import { useForm } from "react-hook-form";

import { Button } from "@/components/ui/Button";
import type { ButtonVariant } from "@/components/ui/Button";
import {
  buildEffectiveTimeIso,
  effectiveTimeActionFormSchema,
  nowEffectiveTimeActionDefaults,
  type EffectiveTimeActionFormValues,
} from "@/lib/validation/versionLifecycleAction";

const inputClass =
  "min-h-11 w-full rounded-md border border-border-subtle bg-surface px-3 text-sm text-ink focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-600 disabled:cursor-not-allowed disabled:bg-surface-subtle disabled:text-ink-muted";
const labelClass = "block text-sm font-medium text-ink";
const errorClass = "text-xs text-red-700";

/** PILOT-SETUP-001B7: the shared "explicit review, then confirm" panel
 * behind both Grade Definition Version and Pack Specification Version
 * activate/retire -- both backend commands take the identical
 * `{ client_command_id, effective_time }` shape (see
 * `versionLifecycleAction.ts`) and both require the same UX: a concise
 * review of what is about to change, an explicit `effective_time`
 * (defaulted to now, never silently reused from another timestamp), and a
 * confirm button that never fires until the operator acts. Never
 * auto-activates or auto-retires as a side effect of any other action. */
export function EffectiveTimeActionPanel({
  heading,
  summary,
  confirmLabel,
  confirmVariant = "primary",
  onCancel,
  onConfirm,
  isPending,
  error,
}: {
  heading: string;
  summary: ReactNode;
  confirmLabel: string;
  confirmVariant?: ButtonVariant;
  onCancel: () => void;
  onConfirm: (effectiveTimeIso: string) => void;
  isPending: boolean;
  error?: string | null;
}) {
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<EffectiveTimeActionFormValues>({
    resolver: zodResolver(effectiveTimeActionFormSchema),
    defaultValues: nowEffectiveTimeActionDefaults(),
    mode: "onBlur",
  });

  function submit(values: EffectiveTimeActionFormValues) {
    onConfirm(buildEffectiveTimeIso(values));
  }

  return (
    <form
      onSubmit={handleSubmit(submit)}
      className="flex flex-col gap-4 rounded-xl border border-border-subtle bg-surface p-4"
    >
      <h3 className="text-sm font-semibold text-ink">{heading}</h3>
      <dl className="grid grid-cols-1 gap-2 rounded-md bg-surface-subtle p-3 text-sm sm:grid-cols-2">{summary}</dl>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <label className="flex flex-col gap-1">
          <span className={labelClass}>Effective date</span>
          <input type="date" {...register("effective_date")} className={inputClass} />
          {errors.effective_date?.message && <span className={errorClass}>{errors.effective_date.message}</span>}
        </label>
        <label className="flex flex-col gap-1">
          <span className={labelClass}>Effective time</span>
          <input type="time" {...register("effective_time_of_day")} className={inputClass} />
          {errors.effective_time_of_day?.message && (
            <span className={errorClass}>{errors.effective_time_of_day.message}</span>
          )}
        </label>
      </div>

      {error && (
        <p role="alert" className={errorClass}>
          {error}
        </p>
      )}

      <div className="flex gap-3">
        <Button type="button" variant="secondary" onClick={onCancel} disabled={isPending}>
          Cancel
        </Button>
        <Button type="submit" variant={confirmVariant} disabled={isPending}>
          {isPending ? "Submitting…" : confirmLabel}
        </Button>
      </div>
    </form>
  );
}
