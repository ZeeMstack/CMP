"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";

import { Button } from "@/components/ui/Button";
import type { WorkflowStageRead, WorkflowTransitionCreate } from "@/lib/api/client";
import {
  DEFAULT_WORKFLOW_TRANSITION_FORM_VALUES,
  buildWorkflowTransitionCreatePayload,
  workflowTransitionFormSchema,
  type WorkflowTransitionFormValues,
} from "@/lib/validation/workflowTransition";

const inputClass =
  "min-h-11 w-full rounded-md border border-border-subtle bg-surface px-3 text-sm text-ink focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-600 disabled:cursor-not-allowed disabled:bg-surface-subtle disabled:text-ink-muted";
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

/** PILOT-SETUP-001B6: From/To are always selected from this draft version's
 * own already-created Stages -- never a typed id. A Workflow Transition is
 * a configuration-time permission ("this stage may move to that one"), not
 * a physical Movement -- recording an actual Movement is a separate,
 * unrelated command elsewhere in the app. */
export function WorkflowTransitionForm({
  stages,
  onSubmit,
  onCancel,
  isSubmitting,
  serverError,
}: {
  stages: WorkflowStageRead[];
  onSubmit: (payload: WorkflowTransitionCreate) => void;
  onCancel: () => void;
  isSubmitting: boolean;
  serverError?: string | null;
}) {
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<WorkflowTransitionFormValues>({
    resolver: zodResolver(workflowTransitionFormSchema),
    defaultValues: DEFAULT_WORKFLOW_TRANSITION_FORM_VALUES,
    mode: "onBlur",
  });

  function submit(values: WorkflowTransitionFormValues) {
    onSubmit(buildWorkflowTransitionCreatePayload(values));
  }

  return (
    <form onSubmit={handleSubmit(submit)} className="flex flex-col gap-4 rounded-xl border border-border-subtle bg-surface p-4">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <Field label="From stage" error={errors.from_stage_id?.message}>
          <select {...register("from_stage_id")} className={inputClass}>
            <option value="">Select a stage…</option>
            {stages.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name} ({s.code})
              </option>
            ))}
          </select>
        </Field>
        <Field label="To stage" error={errors.to_stage_id?.message}>
          <select {...register("to_stage_id")} className={inputClass}>
            <option value="">Select a stage…</option>
            {stages.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name} ({s.code})
              </option>
            ))}
          </select>
        </Field>
        <Field label="Code" error={errors.code?.message}>
          <input {...register("code")} className={inputClass} placeholder="TO_GERMINATION" />
        </Field>
        <Field label="Name" error={errors.name?.message}>
          <input {...register("name")} className={inputClass} placeholder="Move to Germination" />
        </Field>
      </div>

      {serverError && (
        <p role="alert" className={errorClass}>
          {serverError}
        </p>
      )}

      <div className="flex gap-3">
        <Button type="button" variant="secondary" onClick={onCancel} disabled={isSubmitting}>
          Cancel
        </Button>
        <Button type="submit" variant="primary" disabled={isSubmitting || stages.length < 2}>
          {isSubmitting ? "Adding…" : "Add transition"}
        </Button>
      </div>
    </form>
  );
}
