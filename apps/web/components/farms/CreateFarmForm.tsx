"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";

import { Button } from "@/components/ui/Button";
import type { FarmCreate } from "@/lib/api/client";
import {
  DEFAULT_CREATE_FARM_FORM_VALUES,
  buildFarmCreatePayload,
  createFarmFormSchema,
  type CreateFarmFormValues,
} from "@/lib/validation/farm";

const inputClass =
  "min-h-11 w-full rounded-md border border-border-subtle bg-surface px-3 text-sm text-ink focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-600";
const labelClass = "block text-sm font-medium text-ink";
const hintClass = "block text-xs text-ink-muted";
const errorClass = "block text-xs text-red-700";

function Field({
  id, label, hint, error, children,
}: { id: string; label: string; hint?: string; error?: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1">
      <label htmlFor={id} className={labelClass}>{label}</label>
      {hint && <span id={`${id}-hint`} className={hintClass}>{hint}</span>}
      {children}
      {error && <span id={`${id}-error`} role="alert" className={errorClass}>{error}</span>}
    </div>
  );
}

function describedBy(id: string, hasHint: boolean, hasError: boolean): string | undefined {
  const ids = [hasHint ? `${id}-hint` : null, hasError ? `${id}-error` : null].filter(Boolean);
  return ids.length > 0 ? ids.join(" ") : undefined;
}

/** Single-page form, not a multi-step wizard -- five fields does not
 * warrant the configure/review split used elsewhere (e.g.
 * `CreateTenantForm`, `GreenhouseSetupForm`). Entered values are never
 * cleared on a failed submit: react-hook-form only resets on an explicit
 * `reset()` call, which this component never makes. */
export function CreateFarmForm({
  onSubmit, isSubmitting, serverError,
}: {
  onSubmit: (payload: FarmCreate) => void;
  isSubmitting: boolean;
  serverError?: string | null;
}) {
  const {
    register, handleSubmit, formState: { errors },
  } = useForm<CreateFarmFormValues>({
    resolver: zodResolver(createFarmFormSchema),
    defaultValues: DEFAULT_CREATE_FARM_FORM_VALUES,
    mode: "onBlur",
  });

  function submit(values: CreateFarmFormValues) {
    onSubmit(buildFarmCreatePayload(values));
  }

  return (
    <form onSubmit={handleSubmit(submit)} noValidate className="flex flex-col gap-6">
      <fieldset className="flex flex-col gap-4 rounded-xl border border-border-subtle bg-surface p-4">
        <legend className="px-1 text-sm font-semibold text-ink">Farm identity</legend>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Field id="farm-code" label="Farm code" error={errors.code?.message}>
            <input
              id="farm-code"
              aria-invalid={Boolean(errors.code)}
              aria-describedby={describedBy("farm-code", false, Boolean(errors.code))}
              {...register("code")}
              className={inputClass}
              placeholder="FARM-01"
            />
          </Field>
          <Field id="farm-name" label="Farm name" error={errors.name?.message}>
            <input
              id="farm-name"
              aria-invalid={Boolean(errors.name)}
              aria-describedby={describedBy("farm-name", false, Boolean(errors.name))}
              {...register("name")}
              className={inputClass}
              placeholder="Acme Farms — Site 1"
            />
          </Field>
        </div>
      </fieldset>

      <fieldset className="flex flex-col gap-4 rounded-xl border border-border-subtle bg-surface p-4">
        <legend className="px-1 text-sm font-semibold text-ink">Location</legend>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Field
            id="farm-country-code"
            label="Country code (ISO-2)"
            hint="Two-letter country code, e.g. PK"
            error={errors.countryCode?.message}
          >
            <input
              id="farm-country-code"
              aria-invalid={Boolean(errors.countryCode)}
              aria-describedby={describedBy("farm-country-code", true, Boolean(errors.countryCode))}
              {...register("countryCode")}
              className={inputClass}
              placeholder="PK"
              maxLength={2}
            />
          </Field>
          <Field id="farm-city-region" label="City / region (optional)" error={errors.cityRegion?.message}>
            <input
              id="farm-city-region"
              aria-invalid={Boolean(errors.cityRegion)}
              aria-describedby={describedBy("farm-city-region", false, Boolean(errors.cityRegion))}
              {...register("cityRegion")}
              className={inputClass}
              placeholder="Lahore"
            />
          </Field>
          <Field
            id="farm-timezone"
            label="Timezone"
            hint="IANA timezone, e.g. Asia/Karachi"
            error={errors.timezone?.message}
          >
            <input
              id="farm-timezone"
              aria-invalid={Boolean(errors.timezone)}
              aria-describedby={describedBy("farm-timezone", true, Boolean(errors.timezone))}
              {...register("timezone")}
              className={inputClass}
              placeholder="Asia/Karachi"
            />
          </Field>
        </div>
      </fieldset>

      {serverError && (
        <p role="alert" className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
          {serverError}
        </p>
      )}

      <div>
        <Button type="submit" variant="primary" disabled={isSubmitting}>
          {isSubmitting ? "Creating…" : "Create Farm"}
        </Button>
      </div>
    </form>
  );
}
