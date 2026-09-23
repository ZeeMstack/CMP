"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { useForm } from "react-hook-form";

import { Button } from "@/components/ui/Button";
import type { EquipmentIncidentOpenIn } from "@/lib/api/client";
import {
  EQUIPMENT_INCIDENT_CATEGORY_LABELS,
  equipmentIncidentCategoryOptions,
  equipmentIncidentSeverityOptions,
  equipmentIncidentFormSchema,
  buildEquipmentIncidentOpenPayload,
  defaultEquipmentIncidentFormValues,
  type EquipmentIncidentFormValues,
} from "@/lib/validation/equipmentIncident";
import { humanizeEnumCode } from "@/lib/format/humanize";

const inputClass =
  "min-h-11 w-full rounded-md border border-wl-border bg-wl-surface-raised px-3 text-sm text-wl-text focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-wl-focus";
const labelClass = "block text-sm font-medium text-wl-text";
const errorClass = "text-xs text-danger-700";

function Field({ label, error, help, children }: { label: string; error?: string; help?: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1">
      <span className={labelClass}>{label}</span>
      {children}
      {help && <span className="text-xs text-wl-text-secondary">{help}</span>}
      {error && <span className={errorClass}>{error}</span>}
    </label>
  );
}

export interface EquipmentIncidentOption {
  id: string;
  label: string;
}

/** PILOT-ASSET-001/UX-OPS-001B: Report Incident -- mirrors
 * `PlaceTrolleyForm.tsx`'s shape (single-purpose form). `client_command_id`
 * is minted ONCE per form draft (ticket §8.2: "do not mint a new UUID on
 * every click") and reused across a retry of the same payload -- a fresh
 * mount (a genuinely new report) is the only thing that mints a new one. */
export function ReportIncidentForm({
  assets,
  locationOptions,
  lockedAssetId,
  onSubmit,
  onCancel,
  isSubmitting,
  serverError,
}: {
  assets: EquipmentIncidentOption[];
  locationOptions: EquipmentIncidentOption[];
  lockedAssetId?: string;
  onSubmit: (payload: EquipmentIncidentOpenIn) => void;
  onCancel: () => void;
  isSubmitting: boolean;
  serverError?: string | null;
}) {
  const {
    register, handleSubmit, formState: { errors },
  } = useForm<EquipmentIncidentFormValues>({
    resolver: zodResolver(equipmentIncidentFormSchema),
    defaultValues: defaultEquipmentIncidentFormValues(lockedAssetId),
    mode: "onBlur",
  });
  const [clientCommandId] = useState(() => crypto.randomUUID());

  function submit(values: EquipmentIncidentFormValues) {
    onSubmit(buildEquipmentIncidentOpenPayload(values, clientCommandId));
  }

  const lockedAsset = lockedAssetId ? assets.find((a) => a.id === lockedAssetId) : undefined;

  return (
    <form onSubmit={handleSubmit(submit)} className="flex flex-col gap-6">
      <fieldset className="grid grid-cols-1 gap-4 rounded-xl border border-wl-border bg-wl-surface-raised p-4 sm:grid-cols-2">
        <legend className="px-1 text-sm font-semibold text-wl-text">Equipment</legend>
        {lockedAssetId ? (
          <Field label="Asset">
            <p className={`${inputClass} flex items-center bg-wl-surface-sunken text-wl-text`}>
              {lockedAsset?.label ?? lockedAssetId}
            </p>
          </Field>
        ) : (
          <Field label="Asset" error={errors.assetId?.message}>
            <select {...register("assetId")} className={inputClass}>
              <option value="">Select an Asset…</option>
              {assets.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.label}
                </option>
              ))}
            </select>
          </Field>
        )}
        <Field label="Severity" error={errors.severity?.message}>
          <select {...register("severity")} className={inputClass}>
            {equipmentIncidentSeverityOptions.map((s) => (
              <option key={s} value={s}>
                {humanizeEnumCode(s)}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Category" error={errors.category?.message}>
          <select {...register("category")} className={inputClass}>
            {equipmentIncidentCategoryOptions.map((c) => (
              <option key={c} value={c}>
                {EQUIPMENT_INCIDENT_CATEGORY_LABELS[c]}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Detected at" error={errors.detectedAt?.message}>
          <input type="datetime-local" {...register("detectedAt")} className={inputClass} />
        </Field>
      </fieldset>

      <fieldset className="grid grid-cols-1 gap-4 rounded-xl border border-wl-border bg-wl-surface-raised p-4 sm:grid-cols-2">
        <legend className="px-1 text-sm font-semibold text-wl-text">Location (optional)</legend>
        <Field label="Location">
          <select {...register("locationId")} className={inputClass}>
            <option value="">None</option>
            {locationOptions.map((l) => (
              <option key={l.id} value={l.id}>
                {l.label}
              </option>
            ))}
          </select>
        </Field>
        <Field
          label="Potentially impacted area"
          help="Where this problem MAY affect operations — not a confirmed crop impact."
        >
          <select {...register("potentiallyImpactedLocationId")} className={inputClass}>
            <option value="">None</option>
            {locationOptions.map((l) => (
              <option key={l.id} value={l.id}>
                {l.label}
              </option>
            ))}
          </select>
        </Field>
      </fieldset>

      <fieldset className="flex flex-col gap-4 rounded-xl border border-wl-border bg-wl-surface-raised p-4">
        <legend className="px-1 text-sm font-semibold text-wl-text">Details</legend>
        <Field label="Description" error={errors.description?.message}>
          <textarea {...register("description")} className={`${inputClass} min-h-20`} rows={3} />
        </Field>
        <Field label="Notes (optional)" error={errors.notes?.message}>
          <textarea {...register("notes")} className={`${inputClass} min-h-16`} rows={2} />
        </Field>
      </fieldset>

      {serverError && <p role="alert" className={errorClass}>{serverError}</p>}

      <div className="flex gap-3">
        <Button type="button" variant="secondary" onClick={onCancel} disabled={isSubmitting}>
          Cancel
        </Button>
        <Button type="submit" variant="primary" disabled={isSubmitting}>
          {isSubmitting ? "Reporting…" : "Report Incident"}
        </Button>
      </div>
    </form>
  );
}
