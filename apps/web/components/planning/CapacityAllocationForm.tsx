"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { useForm } from "react-hook-form";

import { Button } from "@/components/ui/Button";
import type { CreateProductionCapacityAllocation } from "@/lib/api/client";
import type { FlattenedLocationCapacityOption } from "@/lib/format/locationTree";
import { useLocationCapacitySummary, useProductionSystems } from "@/lib/query/hooks";
import {
  DEFAULT_CAPACITY_ALLOCATION_FORM_VALUES,
  buildCreateCapacityAllocationPayload,
  capacityAllocationFormSchema,
  type CapacityAllocationFormValues,
} from "@/lib/validation/capacityPlan";

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

/** PILOT-PLAN-001B section 12/13: Create Capacity Allocation, with a live
 * pre-submit preview (configured / already planned / remaining) computed
 * from `GET .../capacity-summary` for the currently entered Location+window
 * -- so a manager sees the same numbers before submitting that the backend
 * will enforce. `capacity_plan_service`'s own 409 body is an unstructured
 * `detail: string` (see docs/domain/HARVEST_FORECAST_CAPACITY_MODEL.md's
 * API surface), so on rejection this shows that message verbatim alongside
 * the last-known preview figures rather than parsing numbers out of it. */
export function CapacityAllocationForm({
  farmId,
  locationOptions,
  defaultLocationId,
  onSubmit,
  onCancel,
  isSubmitting,
  serverError,
}: {
  farmId: string;
  locationOptions: FlattenedLocationCapacityOption[];
  defaultLocationId?: string;
  onSubmit: (payload: CreateProductionCapacityAllocation) => void;
  onCancel: () => void;
  isSubmitting: boolean;
  serverError?: string | null;
}) {
  const {
    register, watch, handleSubmit, formState: { errors },
  } = useForm<CapacityAllocationFormValues>({
    resolver: zodResolver(capacityAllocationFormSchema),
    defaultValues: { ...DEFAULT_CAPACITY_ALLOCATION_FORM_VALUES, location_id: defaultLocationId ?? "" },
    mode: "onBlur",
  });
  const productionSystemsQuery = useProductionSystems();
  const [clientCommandId] = useState(() => crypto.randomUUID());

  const locationId = watch("location_id");
  const startDate = watch("planned_start_date");
  const endDate = watch("planned_end_date");
  const requestedAmount = watch("planned_capacity_amount");

  const previewQuery = useLocationCapacitySummary(
    farmId,
    locationId || undefined,
    startDate,
    endDate,
  );
  const preview = previewQuery.data;
  const requestedNumber = Number(requestedAmount);
  const hasValidPreviewInputs = Boolean(locationId && startDate && endDate && endDate > startDate);

  function submit(values: CapacityAllocationFormValues) {
    onSubmit(buildCreateCapacityAllocationPayload(values, clientCommandId));
  }

  return (
    <form onSubmit={handleSubmit(submit)} className="flex max-w-2xl flex-col gap-4 rounded-lg border border-wl-border bg-wl-surface-raised p-4">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <div className="sm:col-span-2">
          <Field label="Location" error={errors.location_id?.message}>
            <select {...register("location_id")} className={inputClass}>
              <option value="">Select a location…</option>
              {locationOptions.map((option) => (
                <option key={option.id} value={option.id}>
                  {option.label}
                </option>
              ))}
            </select>
          </Field>
        </div>
        <Field label="Start" error={errors.planned_start_date?.message}>
          <input type="date" {...register("planned_start_date")} className={inputClass} />
        </Field>
        <Field label="End (exclusive)" error={errors.planned_end_date?.message}>
          <input type="date" {...register("planned_end_date")} className={inputClass} />
        </Field>
        <Field label="Planned positions" error={errors.planned_capacity_amount?.message}>
          <input inputMode="numeric" {...register("planned_capacity_amount")} className={inputClass} />
        </Field>
        <Field label="Production System (optional)">
          <select {...register("production_system_id")} className={inputClass}>
            <option value="">None</option>
            {productionSystemsQuery.data?.map((system) => (
              <option key={system.id} value={system.id}>
                {system.name}
              </option>
            ))}
          </select>
        </Field>
        <div className="sm:col-span-2">
          <Field label="Notes (optional)" error={errors.notes?.message}>
            <input {...register("notes")} className={inputClass} />
          </Field>
        </div>
      </div>

      {hasValidPreviewInputs && (
        <div className="rounded-md border border-wl-border bg-wl-surface p-3 text-xs text-wl-text-secondary">
          {previewQuery.isLoading && <p>Checking capacity…</p>}
          {previewQuery.error && <p>Could not check capacity for this location/window.</p>}
          {preview && preview.capacity_status === "unknown" && <p>Capacity not configured for this location.</p>}
          {preview && preview.capacity_status === "known" && (
            <dl className="grid grid-cols-2 gap-1 sm:grid-cols-4">
              <div>
                <dt className="text-[10px] uppercase tracking-wide">Configured</dt>
                <dd className="font-medium text-wl-text">{preview.authoritative_capacity} positions</dd>
              </div>
              <div>
                <dt className="text-[10px] uppercase tracking-wide">Already planned</dt>
                <dd className="font-medium text-wl-text">{preview.planned_used_capacity} positions</dd>
              </div>
              <div>
                <dt className="text-[10px] uppercase tracking-wide">Requested</dt>
                <dd className="font-medium text-wl-text">
                  {Number.isFinite(requestedNumber) && requestedNumber > 0 ? requestedNumber : "—"} positions
                </dd>
              </div>
              <div>
                <dt className="text-[10px] uppercase tracking-wide">Remaining after this</dt>
                <dd className="font-medium text-wl-text">
                  {Number.isFinite(requestedNumber) && requestedNumber > 0 && preview.available_planned_capacity !== null
                    ? preview.available_planned_capacity - requestedNumber
                    : preview.available_planned_capacity}{" "}
                  positions
                </dd>
              </div>
            </dl>
          )}
        </div>
      )}

      {serverError && <p role="alert" className={errorClass}>{serverError}</p>}

      <div className="flex gap-2">
        <Button type="submit" variant="primary" disabled={isSubmitting}>
          {isSubmitting ? "Saving…" : "Create allocation"}
        </Button>
        <Button type="button" variant="secondary" onClick={onCancel} disabled={isSubmitting}>
          Cancel
        </Button>
      </div>
    </form>
  );
}
