"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useForm, useWatch } from "react-hook-form";

import { Button } from "@/components/ui/Button";
import type { CarrierSpecificationRead } from "@/lib/api/client";
import {
  DEFAULT_CARRIER_REGISTRATION_FORM_VALUES,
  buildCarrierBulkCreatePayload,
  buildCarrierCreatePayload,
  carrierRegistrationFormSchema,
  generateCarrierCodePreview,
  isSelectableForCarrierRegistration,
  type CarrierRegistrationFormValues,
} from "@/lib/validation/carrierRegistration";

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

function SpecificationContext({ spec }: { spec: CarrierSpecificationRead }) {
  const dims = [spec.length_mm, spec.width_mm, spec.height_mm].every((v) => v === null)
    ? "—"
    : [spec.length_mm, spec.width_mm, spec.height_mm].map((v) => v ?? "–").join(" × ");
  return (
    <dl className="grid grid-cols-2 gap-x-4 gap-y-2 rounded-md border border-border-subtle bg-surface-subtle p-3 text-sm sm:grid-cols-4">
      <div>
        <dt className="text-xs text-ink-muted">Code</dt>
        <dd className="font-medium text-ink">{spec.code}</dd>
      </div>
      <div>
        <dt className="text-xs text-ink-muted">Name</dt>
        <dd className="font-medium text-ink">{spec.name}</dd>
      </div>
      <div>
        <dt className="text-xs text-ink-muted">Carrier type</dt>
        <dd className="font-medium text-ink">{spec.carrier_type_code}</dd>
      </div>
      <div>
        <dt className="text-xs text-ink-muted">Dimensions (mm)</dt>
        <dd className="font-medium text-ink">{dims}</dd>
      </div>
      {spec.biological_position_count !== null && (
        <div>
          <dt className="text-xs text-ink-muted">{spec.biological_position_label ?? "Positions"}</dt>
          <dd className="font-medium text-ink">{spec.biological_position_count}</dd>
        </div>
      )}
    </dl>
  );
}

/** PILOT-SETUP-001B5: registers the reusable PHYSICAL object only -- never
 * a Location, Crop Batch, plant count, or production stage. This form has
 * no field for any of those, by design (see CLAUDE.md / the ticket's own
 * "NO PHYSICAL PLACEMENT" section) -- a registered Carrier is created
 * unoccupied and stays that way until a separate, existing operational
 * placement flow moves it. The CarrierSpecification itself is read-only
 * context here (code/name/type/dimensions/position count); changing a
 * specification's own fields stays on the Carrier Specifications page.
 *
 * FINAL INTEGRITY CLEANUP: `specifications` is filtered again here via
 * `isSelectableForCarrierRegistration`, on top of whatever filtering the
 * caller (the Carriers page) already applied -- the legacy generic
 * `cultivation_plate` type can never appear in the picker, or be selected
 * via a preselected id, no matter which layer a future caller forgets to
 * filter at. */
export function CarrierRegistrationForm({
  specifications,
  isSubmitting,
  serverError,
  onCancel,
  onSubmitSingle,
  onSubmitBulk,
}: {
  specifications: CarrierSpecificationRead[];
  isSubmitting: boolean;
  serverError?: string | null;
  onCancel: () => void;
  onSubmitSingle: (payload: ReturnType<typeof buildCarrierCreatePayload>) => void;
  onSubmitBulk: (payload: ReturnType<typeof buildCarrierBulkCreatePayload>) => void;
}) {
  const {
    register,
    control,
    handleSubmit,
    formState: { errors },
  } = useForm<CarrierRegistrationFormValues>({
    resolver: zodResolver(carrierRegistrationFormSchema),
    defaultValues: DEFAULT_CARRIER_REGISTRATION_FORM_VALUES,
    mode: "onBlur",
  });

  // useWatch (not the `watch()` function useForm returns) -- the plain
  // function is a react-hook-form API the React Compiler cannot memoize
  // safely; useWatch is itself a proper hook subscription and compiles
  // cleanly.
  const mode = useWatch({ control, name: "mode" });
  const specificationId = useWatch({ control, name: "specification_id" });
  const codePrefix = useWatch({ control, name: "code_prefix" });
  const start = useWatch({ control, name: "start" });
  const end = useWatch({ control, name: "end" });
  const padWidth = useWatch({ control, name: "pad_width" });

  const selectableSpecifications = specifications.filter(isSelectableForCarrierRegistration);
  const selectedSpec = selectableSpecifications.find((s) => s.id === specificationId);
  const preview = mode === "bulk" ? generateCarrierCodePreview(codePrefix, start, end, padWidth) : [];

  function submit(values: CarrierRegistrationFormValues) {
    if (values.mode === "single") {
      onSubmitSingle(buildCarrierCreatePayload(values));
    } else {
      onSubmitBulk(buildCarrierBulkCreatePayload(values));
    }
  }

  return (
    <form onSubmit={handleSubmit(submit)} className="flex flex-col gap-6">
      <fieldset className="flex flex-col gap-2">
        <legend className={labelClass}>How many carriers?</legend>
        <div className="flex flex-wrap gap-2">
          {(["single", "bulk"] as const).map((m) => (
            <label
              key={m}
              className={`flex min-h-11 cursor-pointer items-center gap-2 rounded-full border px-4 text-sm font-medium transition-colors ${
                mode === m ? "border-brand-600 bg-brand-100 text-brand-800" : "border-border-subtle text-ink hover:border-brand-300"
              }`}
            >
              <input type="radio" value={m} {...register("mode")} className="sr-only" />
              {m === "single" ? "One carrier" : "A range of carriers"}
            </label>
          ))}
        </div>
      </fieldset>

      <fieldset className="flex flex-col gap-3 rounded-xl border border-border-subtle bg-surface p-4">
        <legend className="px-1 text-sm font-semibold text-ink">Carrier specification</legend>
        <Field label="Specification" error={errors.specification_id?.message}>
          <select {...register("specification_id")} className={inputClass}>
            <option value="">Select an active specification…</option>
            {selectableSpecifications.map((s) => (
              <option key={s.id} value={s.id}>
                {s.code} — {s.name}
              </option>
            ))}
          </select>
        </Field>
        {selectedSpec && <SpecificationContext spec={selectedSpec} />}
      </fieldset>

      {mode === "single" ? (
        <fieldset className="grid grid-cols-1 gap-4 rounded-xl border border-border-subtle bg-surface p-4 sm:grid-cols-2">
          <legend className="px-1 text-sm font-semibold text-ink">Identity</legend>
          <Field label="Carrier code" error={errors.code?.message}>
            <input {...register("code")} className={inputClass} placeholder="STR-0001" />
          </Field>
          <Field label="Issued date (optional)" error={errors.issued_date?.message}>
            <input type="date" {...register("issued_date")} className={inputClass} />
          </Field>
        </fieldset>
      ) : (
        <fieldset className="grid grid-cols-1 gap-4 rounded-xl border border-border-subtle bg-surface p-4 sm:grid-cols-2">
          <legend className="px-1 text-sm font-semibold text-ink">Code range</legend>
          <Field label="Code prefix" error={errors.code_prefix?.message}>
            <input {...register("code_prefix")} className={inputClass} placeholder="STR-" />
          </Field>
          <Field label="Pad width" error={errors.pad_width?.message}>
            <input
              type="number"
              min={1}
              step={1}
              {...register("pad_width", { valueAsNumber: true })}
              className={inputClass}
            />
          </Field>
          <Field label="Start" error={errors.start?.message}>
            <input type="number" min={1} step={1} {...register("start", { valueAsNumber: true })} className={inputClass} />
          </Field>
          <Field label="End" error={errors.end?.message}>
            <input type="number" min={1} step={1} {...register("end", { valueAsNumber: true })} className={inputClass} />
          </Field>
          <div className="sm:col-span-2">
            <span className={labelClass}>Preview ({preview.length} carrier{preview.length === 1 ? "" : "s"})</span>
            {preview.length > 0 ? (
              <p className="mt-1 max-h-24 overflow-y-auto rounded-md border border-border-subtle bg-surface-subtle px-3 py-2 text-xs text-ink-muted">
                {preview.join(", ")}
              </p>
            ) : (
              <p className="mt-1 text-xs text-ink-muted">Enter a prefix, start, end, and pad width to preview codes.</p>
            )}
          </div>
        </fieldset>
      )}

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
          {isSubmitting ? "Registering…" : mode === "single" ? "Register carrier" : "Register carriers"}
        </Button>
      </div>
    </form>
  );
}
