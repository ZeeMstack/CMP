"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useForm, useWatch } from "react-hook-form";

import { Button } from "@/components/ui/Button";
import type { FlattenedLocationOption } from "@/lib/format/locationTree";
import {
  DEFAULT_LOCATION_FORM_VALUES,
  GENERIC_LOCATION_TYPES,
  buildLocationBulkChildrenPayload,
  buildLocationCreatePayload,
  generateLocationCodePreview,
  locationFormSchema,
  type LocationFormValues,
} from "@/lib/validation/location";

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

/** PILOT-SETUP-001B5: one form, two modes -- single create (`POST
 * .../locations`) and range/generator bulk-children (`POST
 * .../locations/{parentId}/bulk-children`), matching the two real backend
 * endpoints exactly. There is no client-side parent/type compatibility
 * filter: the Location tree read model exposes each node's
 * `location_type_id` (an opaque UUID), never its `location_type_code`, and
 * no `GET /location-types` endpoint exists to resolve one to the other --
 * so this form lets the operator pick any existing location as parent and
 * relies on the backend's own `InvalidLocationHierarchyError` (422) to
 * reject an unsupported type/parent combination, surfaced as a plain
 * server-error message below. This is a known, reported UX limitation, not
 * a correctness gap -- the backend remains fully authoritative either way. */
export function LocationCreateForm({
  parentOptions,
  isSubmitting,
  serverError,
  onCancel,
  onSubmitSingle,
  onSubmitBulk,
}: {
  parentOptions: FlattenedLocationOption[];
  isSubmitting: boolean;
  serverError?: string | null;
  onCancel: () => void;
  onSubmitSingle: (payload: ReturnType<typeof buildLocationCreatePayload>) => void;
  onSubmitBulk: (parentId: string, payload: ReturnType<typeof buildLocationBulkChildrenPayload>) => void;
}) {
  const {
    register,
    control,
    handleSubmit,
    formState: { errors },
  } = useForm<LocationFormValues>({
    resolver: zodResolver(locationFormSchema),
    defaultValues: DEFAULT_LOCATION_FORM_VALUES,
    mode: "onBlur",
  });

  // useWatch (not the `watch()` function useForm returns) -- the plain
  // function is a react-hook-form API the React Compiler cannot memoize
  // safely; useWatch is itself a proper hook subscription and compiles
  // cleanly.
  const mode = useWatch({ control, name: "mode" });
  const codePrefix = useWatch({ control, name: "code_prefix" });
  const start = useWatch({ control, name: "start" });
  const end = useWatch({ control, name: "end" });
  const padWidth = useWatch({ control, name: "pad_width" });
  const preview = mode === "bulk" ? generateLocationCodePreview(codePrefix, start, end, padWidth) : [];

  function submit(values: LocationFormValues) {
    if (values.mode === "single") {
      onSubmitSingle(buildLocationCreatePayload(values));
    } else {
      onSubmitBulk(values.parent_location_id, buildLocationBulkChildrenPayload(values));
    }
  }

  return (
    <form onSubmit={handleSubmit(submit)} className="flex flex-col gap-6">
      <fieldset className="flex flex-col gap-2">
        <legend className={labelClass}>How many locations?</legend>
        <div className="flex flex-wrap gap-2">
          {(["single", "bulk"] as const).map((m) => (
            <label
              key={m}
              className={`flex min-h-11 cursor-pointer items-center gap-2 rounded-full border px-4 text-sm font-medium transition-colors ${
                mode === m ? "border-brand-600 bg-brand-100 text-brand-800" : "border-border-subtle text-ink hover:border-brand-300"
              }`}
            >
              <input type="radio" value={m} {...register("mode")} className="sr-only" />
              {m === "single" ? "One location" : "A range of locations"}
            </label>
          ))}
        </div>
      </fieldset>

      <fieldset className="grid grid-cols-1 gap-4 rounded-xl border border-border-subtle bg-surface p-4 sm:grid-cols-2">
        <legend className="px-1 text-sm font-semibold text-ink">Placement</legend>
        <Field label="Location type" error={errors.location_type_code?.message}>
          <select {...register("location_type_code")} className={inputClass}>
            <option value="">Select a location type…</option>
            {GENERIC_LOCATION_TYPES.map((t) => (
              <option key={t.code} value={t.code}>
                {t.label}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Parent location" error={errors.parent_location_id?.message}>
          <select {...register("parent_location_id")} className={inputClass}>
            <option value="">No parent (top-level)</option>
            {parentOptions.map((p) => (
              <option key={p.id} value={p.id}>
                {p.label}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Capacity (optional)" error={errors.capacity?.message}>
          <input
            type="number"
            min={1}
            step={1}
            {...register("capacity", {
              // react-hook-form routes an untouched field's own `null`
              // default through this same transform (not just a raw DOM
              // change-event string) -- without the extra null/undefined
              // guard, `Number(null)` is 0, which then fails `.positive()`
              // even though the operator never touched the field.
              setValueAs: (v) => (v === "" || v === null || v === undefined ? null : Number(v)),
            })}
            className={inputClass}
          />
        </Field>
      </fieldset>

      {mode === "single" ? (
        <fieldset className="grid grid-cols-1 gap-4 rounded-xl border border-border-subtle bg-surface p-4 sm:grid-cols-2">
          <legend className="px-1 text-sm font-semibold text-ink">Identity</legend>
          <Field label="Code" error={errors.code?.message}>
            <input {...register("code")} className={inputClass} placeholder="COLD-01" />
          </Field>
          <Field label="Name" error={errors.name?.message}>
            <input {...register("name")} className={inputClass} placeholder="Cold Store 1" />
          </Field>
        </fieldset>
      ) : (
        <fieldset className="grid grid-cols-1 gap-4 rounded-xl border border-border-subtle bg-surface p-4 sm:grid-cols-2">
          <legend className="px-1 text-sm font-semibold text-ink">Code range</legend>
          <Field label="Code prefix" error={errors.code_prefix?.message}>
            <input {...register("code_prefix")} className={inputClass} placeholder="P" />
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
          <Field label="Name template (optional)" error={errors.name_template?.message}>
            <input {...register("name_template")} className={inputClass} placeholder="Cold-Store Position {code}" />
          </Field>
          <div className="sm:col-span-2">
            <span className={labelClass}>Preview ({preview.length} location{preview.length === 1 ? "" : "s"})</span>
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
          {isSubmitting ? "Creating…" : mode === "single" ? "Create location" : "Create locations"}
        </Button>
      </div>
    </form>
  );
}
