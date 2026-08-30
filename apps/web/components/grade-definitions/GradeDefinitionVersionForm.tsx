"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";

import { Button } from "@/components/ui/Button";
import type { GradeDefinitionVersionCreate } from "@/lib/api/client";
import {
  DEFAULT_GRADE_DEFINITION_VERSION_FORM_VALUES,
  buildGradeDefinitionVersionCreatePayload,
  gradeDefinitionVersionFormSchema,
  type GradeDefinitionVersionFormValues,
} from "@/lib/validation/gradeDefinition";

const inputClass =
  "min-h-11 w-full rounded-md border border-border-subtle bg-surface px-3 text-sm text-ink focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-600 disabled:cursor-not-allowed disabled:bg-surface-subtle disabled:text-ink-muted";
const labelClass = "block text-sm font-medium text-ink";
const errorClass = "text-xs text-red-700";

/** PILOT-SETUP-001B7: creates a new DRAFT version only -- the backend never
 * activates a version as a side effect of this command (see
 * `grade_definition_service.create_draft_version`), so this form never
 * offers an "activate immediately" shortcut. Activation is always the
 * separate, explicit follow-on step the version catalog offers per row. */
export function GradeDefinitionVersionForm({
  onSubmit,
  onCancel,
  isSubmitting,
  serverError,
}: {
  onSubmit: (payload: GradeDefinitionVersionCreate) => void;
  onCancel: () => void;
  isSubmitting: boolean;
  serverError?: string | null;
}) {
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<GradeDefinitionVersionFormValues>({
    resolver: zodResolver(gradeDefinitionVersionFormSchema),
    defaultValues: DEFAULT_GRADE_DEFINITION_VERSION_FORM_VALUES,
    mode: "onBlur",
  });

  function submit(values: GradeDefinitionVersionFormValues) {
    onSubmit(buildGradeDefinitionVersionCreatePayload(values, crypto.randomUUID()));
  }

  return (
    <form onSubmit={handleSubmit(submit)} className="flex flex-col gap-4 rounded-xl border border-border-subtle bg-surface p-4">
      <label className="flex flex-col gap-1">
        <span className={labelClass}>Spec notes (optional)</span>
        <textarea {...register("spec_notes")} rows={4} className={`${inputClass} min-h-0 py-2`} />
        {errors.spec_notes?.message && <span className={errorClass}>{errors.spec_notes.message}</span>}
      </label>

      {serverError && (
        <p role="alert" className={errorClass}>
          {serverError}
        </p>
      )}

      <div className="flex gap-3">
        <Button type="button" variant="secondary" onClick={onCancel} disabled={isSubmitting}>
          Cancel
        </Button>
        <Button type="submit" variant="primary" disabled={isSubmitting}>
          {isSubmitting ? "Creating…" : "Create draft version"}
        </Button>
      </div>
    </form>
  );
}
