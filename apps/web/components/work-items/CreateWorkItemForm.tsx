"use client";

import { useState } from "react";

import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";

import { Button } from "@/components/ui/Button";
import { humanizeEnumCode } from "@/lib/format/humanize";
import type { FarmWorkItemCreate } from "@/lib/api/client";
import {
  DEFAULT_FARM_WORK_ITEM_FORM_VALUES,
  buildFarmWorkItemCreatePayload,
  farmWorkItemFormSchema,
  workItemCategoryOptions,
  workItemPriorityOptions,
  type FarmWorkItemFormValues,
} from "@/lib/validation/farmWorkItem";

const inputClass =
  "min-h-11 w-full rounded-md border border-wl-border bg-wl-surface-raised px-3 text-sm text-wl-text focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-wl-focus";
const labelClass = "block text-sm font-medium text-wl-text";
const errorClass = "text-xs text-danger-700";

function Field({ label, error, children }: { label: string; error?: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1">
      <span className={labelClass}>{label}</span>
      {children}
      {error && <span className={errorClass}>{error}</span>}
    </label>
  );
}

/** One (id, label) option for a context select -- every option's `id` is
 * the real authoritative entity id (a Location/Batch/Asset/Carrier row),
 * never a display string alone. PILOT-SCAN-001 will later resolve the
 * same ids from a QR scan. */
export interface WorkItemContextOption {
  id: string;
  label: string;
}

function ContextSelect({
  label, value, options, onChange, disabled,
}: {
  label: string;
  value: string;
  options: WorkItemContextOption[];
  onChange: (value: string) => void;
  disabled?: boolean;
}) {
  return (
    <Field label={label}>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className={inputClass}
        disabled={disabled || options.length === 0}
      >
        <option value="">None</option>
        {options.map((o) => (
          <option key={o.id} value={o.id}>
            {o.label}
          </option>
        ))}
      </select>
      {!disabled && options.length === 0 && <span className="text-xs text-wl-text-secondary">None available</span>}
    </Field>
  );
}

/** PILOT-OPS-001 closure: compact manual Work Item creation, with optional
 * structured Location/Batch/Asset/Carrier context behind an "Add context"
 * disclosure -- keeps the routine (no-context) case exactly as compact as
 * before. Every option list is caller-supplied (already-fetched farm data,
 * never a second request this form triggers itself) -- see
 * app/farms/[farmId]/page.tsx for what feeds each list. */
export function CreateWorkItemForm({
  onSubmit,
  onCancel,
  isSubmitting,
  serverError,
  currentUserId,
  locationOptions = [],
  batchOptions = [],
  assetOptions = [],
  carrierOptions = [],
  equipmentIncidentOptions = [],
  lockedCropIssue,
  lockedEquipmentIncident,
}: {
  onSubmit: (payload: FarmWorkItemCreate) => void;
  onCancel: () => void;
  isSubmitting: boolean;
  serverError?: string | null;
  currentUserId?: string;
  locationOptions?: WorkItemContextOption[];
  batchOptions?: WorkItemContextOption[];
  assetOptions?: WorkItemContextOption[];
  carrierOptions?: WorkItemContextOption[];
  /** PILOT-ASSET-001: open Equipment Incidents this Work Item may be linked
   * to via the "Add context" disclosure. Only rendered when neither locked
   * prop is set (mirrors `lockedCropIssue`'s own "editable only when not
   * locked" convention). */
  equipmentIncidentOptions?: WorkItemContextOption[];
  /** PILOT-AGRO-001B: set when opened from a Crop Issue's "Assign
   * corrective work" action -- fixes `crop_issue_id` (and its Batch, when
   * known) as read-only context rather than an editable dropdown, since
   * the backend accepts `crop_issue_id` only at creation, never retrofit. */
  lockedCropIssue?: { id: string; code: string; batchId?: string; batchLabel?: string };
  /** PILOT-ASSET-001: mirrors `lockedCropIssue` exactly -- set when opened
   * from an Equipment Incident's own "Assign corrective work" action. */
  lockedEquipmentIncident?: { id: string; code: string };
}) {
  const [showContext, setShowContext] = useState(false);
  // UX-OPS-001B R1: minted once per form draft (this component mounts
  // fresh each time the create form opens and unmounts on cancel/success),
  // reused across a retry of the same payload -- never regenerated inside
  // submit(), which react-hook-form calls again on every resubmission.
  const [clientCommandId] = useState(() => crypto.randomUUID());
  const {
    register,
    handleSubmit,
    watch,
    setValue,
    formState: { errors },
  } = useForm<FarmWorkItemFormValues>({
    resolver: zodResolver(farmWorkItemFormSchema),
    defaultValues: {
      ...DEFAULT_FARM_WORK_ITEM_FORM_VALUES,
      category: lockedCropIssue
        ? "crop_care"
        : lockedEquipmentIncident
          ? "maintenance"
          : DEFAULT_FARM_WORK_ITEM_FORM_VALUES.category,
      cropIssueId: lockedCropIssue?.id ?? null,
      cropBatchId: lockedCropIssue?.batchId ?? null,
      equipmentIncidentId: lockedEquipmentIncident?.id ?? null,
    },
    mode: "onBlur",
  });

  function submit(values: FarmWorkItemFormValues) {
    onSubmit(buildFarmWorkItemCreatePayload(values, { clientCommandId, currentUserId }));
  }

  // Bound once at the top level (never called inline in JSX) -- mirrors
  // this codebase's own established `watch()` convention (e.g.
  // RequirementForm.tsx, GreenhouseSetupForm.tsx).
  const locationId = watch("locationId");
  const cropBatchId = watch("cropBatchId");
  const assetId = watch("assetId");
  const carrierId = watch("carrierId");
  const equipmentIncidentId = watch("equipmentIncidentId");

  const hasContextOptions =
    locationOptions.length > 0 || batchOptions.length > 0 || assetOptions.length > 0 || carrierOptions.length > 0 ||
    equipmentIncidentOptions.length > 0;

  return (
    <form onSubmit={handleSubmit(submit)} className="flex flex-col gap-4 rounded-xl border border-wl-border bg-wl-surface-raised p-4">
      {lockedCropIssue && (
        <p className="rounded-md bg-wl-surface-sunken px-3 py-2 text-xs text-wl-text-secondary">
          Corrective work for Crop Issue <span className="font-medium text-wl-text">{lockedCropIssue.code}</span>
          {lockedCropIssue.batchLabel ? ` · ${lockedCropIssue.batchLabel}` : ""}
        </p>
      )}
      {lockedEquipmentIncident && (
        <p className="rounded-md bg-wl-surface-sunken px-3 py-2 text-xs text-wl-text-secondary">
          Corrective work for Equipment Incident{" "}
          <span className="font-medium text-wl-text">{lockedEquipmentIncident.code}</span>
        </p>
      )}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <Field label="Title" error={errors.title?.message}>
          <input {...register("title")} className={inputClass} placeholder="Clean Germination Trolley 03" />
        </Field>
        <Field label="Work type" error={errors.workType?.message}>
          <input {...register("workType")} className={inputClass} placeholder="cleaning" />
        </Field>
        <Field label="Category" error={errors.category?.message}>
          <select {...register("category")} className={inputClass}>
            {workItemCategoryOptions.map((c) => (
              <option key={c} value={c}>
                {humanizeEnumCode(c)}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Priority" error={errors.priority?.message}>
          <select {...register("priority")} className={inputClass}>
            {workItemPriorityOptions.map((p) => (
              <option key={p} value={p}>
                {humanizeEnumCode(p)}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Due (optional)" error={errors.dueAt?.message}>
          <input type="datetime-local" {...register("dueAt")} className={inputClass} />
        </Field>
        <label className="flex items-center gap-2 self-end pb-2.5 text-sm text-wl-text">
          <input type="checkbox" {...register("assignToMe")} className="h-4 w-4" disabled={!currentUserId} />
          Assign to me
        </label>
      </div>
      <Field label="Instructions (optional)" error={errors.instructions?.message}>
        <textarea {...register("instructions")} rows={2} className={`${inputClass} min-h-0 py-2`} />
      </Field>

      {!showContext ? (
        <button
          type="button"
          onClick={() => setShowContext(true)}
          className="self-start text-sm font-medium text-wl-brand hover:underline"
        >
          + Add context (location, batch, asset, carrier)
        </button>
      ) : (
        <fieldset className="grid grid-cols-1 gap-4 rounded-lg border border-wl-border p-3 sm:grid-cols-2">
          <legend className="px-1 text-xs font-semibold uppercase tracking-wide text-wl-text-secondary">
            Where / what this work belongs to (optional)
          </legend>
          <ContextSelect
            label="Location"
            value={locationId ?? ""}
            options={locationOptions}
            onChange={(v) => setValue("locationId", v || null)}
          />
          {!lockedCropIssue && (
            <ContextSelect
              label="Batch"
              value={cropBatchId ?? ""}
              options={batchOptions}
              onChange={(v) => setValue("cropBatchId", v || null)}
            />
          )}
          <ContextSelect
            label="Asset"
            value={assetId ?? ""}
            options={assetOptions}
            onChange={(v) => setValue("assetId", v || null)}
          />
          <ContextSelect
            label="Carrier"
            value={carrierId ?? ""}
            options={carrierOptions}
            onChange={(v) => setValue("carrierId", v || null)}
          />
          {!lockedCropIssue && !lockedEquipmentIncident && (
            <ContextSelect
              label="Equipment Incident"
              value={equipmentIncidentId ?? ""}
              options={equipmentIncidentOptions}
              onChange={(v) => setValue("equipmentIncidentId", v || null)}
            />
          )}
          {!hasContextOptions && (
            <p className="sm:col-span-2 text-xs text-wl-text-secondary">
              No locations, batches, assets, or carriers found for this farm yet.
            </p>
          )}
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
          {isSubmitting ? "Creating…" : "Create work item"}
        </Button>
      </div>
    </form>
  );
}
