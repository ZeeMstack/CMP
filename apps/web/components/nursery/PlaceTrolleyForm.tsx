"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { useForm } from "react-hook-form";

import type { PlaceTrolleyCreate } from "@/lib/api/client";
import { useAssets, useAvailableChambers } from "@/lib/query/hooks";
import {
  DEFAULT_PLACE_TROLLEY_FORM_VALUES,
  buildPlaceTrolleyPayload,
  placeTrolleyFormSchema,
  type PlaceTrolleyFormValues,
} from "@/lib/validation/germination";

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

/** GT-01 (Trolley Asset Type) into a Germination Chamber. Both a first
 * placement and a Chamber-to-Chamber move go through the same command --
 * the backend resolves the real current source itself, never accepted
 * from this form. */
export function PlaceTrolleyForm({
  farmId, onSubmit, onCancel, isSubmitting, serverError,
}: {
  farmId: string;
  onSubmit: (payload: PlaceTrolleyCreate) => void;
  onCancel: () => void;
  isSubmitting: boolean;
  serverError?: string | null;
}) {
  const [step, setStep] = useState<"configure" | "review">("configure");
  const [clientCommandId] = useState(() => crypto.randomUUID());

  const initial = nowDateAndTime();
  const {
    register, trigger, getValues, formState: { errors },
  } = useForm<PlaceTrolleyFormValues>({
    resolver: zodResolver(placeTrolleyFormSchema),
    defaultValues: { ...DEFAULT_PLACE_TROLLEY_FORM_VALUES, effective_date: initial.date, effective_time_of_day: initial.time },
    mode: "onBlur",
  });

  const trolleysQuery = useAssets(farmId, "germination_trolley");
  const chambersQuery = useAvailableChambers(farmId);
  const chambers = chambersQuery.data ?? [];

  async function goToReview() {
    const valid = await trigger();
    if (valid) setStep("review");
  }

  function submitReview() {
    onSubmit(buildPlaceTrolleyPayload(getValues(), clientCommandId));
  }

  if (step === "review") {
    const values = getValues();
    const trolley = trolleysQuery.data?.find((t) => t.id === values.trolley_id);
    const chamber = chambers.find((c) => c.id === values.chamber_id);
    return (
      <div className="flex flex-col gap-4">
        <div className="flex flex-col gap-4 rounded-lg border border-border-subtle bg-surface p-4">
          <h2 className="text-sm font-semibold text-ink">Review before placing</h2>
          <p className="text-sm text-ink">
            Place <span className="font-medium">{trolley?.code}</span> in Germination Chamber{" "}
            <span className="font-medium">{chamber?.code}</span>
          </p>
          <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm sm:grid-cols-3">
            <div>
              <dt className="text-ink-muted">Chamber capacity</dt>
              <dd className="font-medium text-ink">{chamber?.trolley_capacity ?? "Unlimited"}</dd>
            </div>
            <div>
              <dt className="text-ink-muted">Currently placed</dt>
              <dd className="font-medium text-ink">{chamber?.active_trolley_count}</dd>
            </div>
            <div>
              <dt className="text-ink-muted">Remaining capacity</dt>
              <dd className="font-medium text-ink">{chamber?.remaining_capacity}</dd>
            </div>
            <div>
              <dt className="text-ink-muted">Occurred at</dt>
              <dd className="font-medium text-ink">
                {values.effective_date} {values.effective_time_of_day}
              </dd>
            </div>
          </dl>
        </div>
        {serverError && <p role="alert" className={errorClass}>{serverError}</p>}
        <div className="flex gap-3">
          <button
            type="button"
            onClick={() => setStep("configure")}
            disabled={isSubmitting}
            className="min-h-11 rounded-md border border-border-subtle px-4 text-sm font-medium text-ink hover:bg-surface-subtle"
          >
            Back
          </button>
          <button
            type="button"
            onClick={submitReview}
            disabled={isSubmitting}
            className="min-h-11 rounded-md bg-brand-700 px-4 text-sm font-medium text-white hover:bg-brand-800 disabled:opacity-60"
          >
            {isSubmitting ? "Placing…" : "Place Trolley"}
          </button>
        </div>
      </div>
    );
  }

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        goToReview();
      }}
      className="flex flex-col gap-6"
    >
      <fieldset className="flex flex-col gap-4 rounded-lg border border-border-subtle p-4">
        <legend className="px-1 text-sm font-semibold text-ink">Trolley</legend>
        <Field label="Trolley" error={errors.trolley_id?.message}>
          <select {...register("trolley_id")} className={inputClass}>
            <option value="">Select a Trolley…</option>
            {trolleysQuery.data?.map((trolley) => (
              <option key={trolley.id} value={trolley.id}>
                {trolley.code}
              </option>
            ))}
          </select>
        </Field>
      </fieldset>

      <fieldset className="flex flex-col gap-4 rounded-lg border border-border-subtle p-4">
        <legend className="px-1 text-sm font-semibold text-ink">Germination Chamber</legend>
        {chambersQuery.isSuccess && chambers.length === 0 ? (
          <p className="text-sm text-ink-muted">No Germination Chambers are configured for this farm yet.</p>
        ) : (
          <Field label="Germination Chamber" error={errors.chamber_id?.message}>
            <select {...register("chamber_id")} className={inputClass}>
              <option value="">Select a Germination Chamber…</option>
              {chambers.map((chamber) => (
                <option key={chamber.id} value={chamber.id}>
                  {chamber.code} — {chamber.remaining_capacity} of {chamber.trolley_capacity ?? "∞"} remaining
                </option>
              ))}
            </select>
          </Field>
        )}
      </fieldset>

      <fieldset className="grid grid-cols-1 gap-4 rounded-lg border border-border-subtle p-4 sm:grid-cols-2">
        <legend className="px-1 text-sm font-semibold text-ink">Placement date/time</legend>
        <Field label="Date" error={errors.effective_date?.message}>
          <input type="date" {...register("effective_date")} className={inputClass} />
        </Field>
        <Field label="Time" error={errors.effective_time_of_day?.message}>
          <input type="time" {...register("effective_time_of_day")} className={inputClass} />
        </Field>
      </fieldset>

      <fieldset className="flex flex-col gap-4 rounded-lg border border-border-subtle p-4">
        <legend className="px-1 text-sm font-semibold text-ink">Reason (optional)</legend>
        <textarea {...register("reason")} className={`${inputClass} min-h-20`} rows={2} />
      </fieldset>

      <div className="flex gap-3">
        <button
          type="button"
          onClick={onCancel}
          className="min-h-11 rounded-md border border-border-subtle px-4 text-sm font-medium text-ink hover:bg-surface-subtle"
        >
          Cancel
        </button>
        <button
          type="submit"
          className="min-h-11 rounded-md bg-brand-700 px-4 text-sm font-medium text-white hover:bg-brand-800"
        >
          Review
        </button>
      </div>
    </form>
  );
}
