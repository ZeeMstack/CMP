"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { useForm } from "react-hook-form";

import { Button } from "@/components/ui/Button";
import type { ProductionCapacityAllocationRead, UpdateProductionCapacityAllocation } from "@/lib/api/client";
import { useProductionSystems } from "@/lib/query/hooks";
import {
  buildUpdateCapacityAllocationPayload,
  capacityAllocationUpdateFormSchema,
  type CapacityAllocationUpdateFormValues,
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

/** PILOT-PLAN-001B section 14: Update Allocation -- a full-replace command
 * (mirrors `RequirementUpdateForm`'s own shape), only while `status ===
 * "active"`. `location_id`/source links have no update path (see
 * docs/domain/HARVEST_FORECAST_CAPACITY_MODEL.md's Part 5 API surface). */
export function CapacityAllocationUpdateForm({
  allocation,
  onSubmit,
  onCancel,
  isSubmitting,
  serverError,
}: {
  allocation: ProductionCapacityAllocationRead;
  onSubmit: (payload: UpdateProductionCapacityAllocation) => void;
  onCancel: () => void;
  isSubmitting: boolean;
  serverError?: string | null;
}) {
  const {
    register, handleSubmit, formState: { errors },
  } = useForm<CapacityAllocationUpdateFormValues>({
    resolver: zodResolver(capacityAllocationUpdateFormSchema),
    defaultValues: {
      production_system_id: allocation.production_system_id ?? "",
      planned_start_date: allocation.planned_start_date,
      planned_end_date: allocation.planned_end_date,
      planned_capacity_amount: String(allocation.planned_capacity_amount),
      notes: allocation.notes ?? "",
    },
    mode: "onBlur",
  });
  const productionSystemsQuery = useProductionSystems();
  const [clientCommandId] = useState(() => crypto.randomUUID());

  function submit(values: CapacityAllocationUpdateFormValues) {
    onSubmit(buildUpdateCapacityAllocationPayload(values, clientCommandId));
  }

  return (
    <form onSubmit={handleSubmit(submit)} className="flex flex-col gap-3 rounded-md border border-wl-border bg-wl-surface p-3">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
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
      {serverError && <p role="alert" className={errorClass}>{serverError}</p>}
      <div className="flex gap-2">
        <Button type="submit" variant="primary" disabled={isSubmitting}>
          {isSubmitting ? "Saving…" : "Save changes"}
        </Button>
        <Button type="button" variant="secondary" onClick={onCancel} disabled={isSubmitting}>
          Cancel
        </Button>
      </div>
    </form>
  );
}
