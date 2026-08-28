"use client";

import { useEffect, useRef } from "react";
import type { FieldErrors, UseFormRegister, UseFormSetValue } from "react-hook-form";

import type { FinishedGoodsLotRead } from "@/lib/api/client";
import { useFinishedGoodsPlacement } from "@/lib/query/hooks";
import type { RecordDispatchFormValues } from "@/lib/validation/dispatch";

const inputClass =
  "min-h-11 w-full rounded-md border border-border-subtle bg-surface px-3 text-sm text-ink focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-600";
const labelClass = "block text-xs font-medium text-ink-muted";
const errorClass = "text-xs text-red-700";

/** PILOT-READY-001: one Finished Goods Lot line inside the Dispatch form.
 * Fetches this Lot's own live Placement (own component instance per line,
 * same rationale as `PackingInputLineRow`'s own per-row cascade) and seeds
 * `dispatched_weight_kg`/`dispatched_package_count` from its currently
 * *unplaced* balance -- CMP-018: dispatch may only ever consume unplaced
 * quantity, so a Lot with stock still placed in Cold Storage shows less
 * (or zero) available balance here than its raw commercial balance until
 * it is released. */
export function DispatchLineRow({
  lot,
  farmId,
  index,
  register,
  setValue,
  errors,
}: {
  lot: FinishedGoodsLotRead;
  farmId: string;
  index: number;
  register: UseFormRegister<RecordDispatchFormValues>;
  setValue: UseFormSetValue<RecordDispatchFormValues>;
  errors: FieldErrors<RecordDispatchFormValues>;
}) {
  const placementQuery = useFinishedGoodsPlacement(farmId, lot.id);
  const hasSeeded = useRef(false);
  const rowErrors = errors.lines?.[index];

  useEffect(() => {
    if (hasSeeded.current || !placementQuery.data) return;
    hasSeeded.current = true;
    setValue(`lines.${index}.available_weight_kg`, Number(placementQuery.data.unplaced_weight_kg));
    setValue(`lines.${index}.available_package_count`, placementQuery.data.unplaced_package_count);
    setValue(`lines.${index}.dispatched_weight_kg`, Number(placementQuery.data.unplaced_weight_kg));
    setValue(`lines.${index}.dispatched_package_count`, placementQuery.data.unplaced_package_count);
  }, [placementQuery.data, index, setValue]);

  return (
    <li className="rounded-md border border-border-subtle p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="text-sm font-semibold text-ink">{lot.code}</span>
        <span className="text-xs text-ink-muted">
          Unplaced{" "}
          {placementQuery.data
            ? `${placementQuery.data.unplaced_weight_kg} kg / ${placementQuery.data.unplaced_package_count} pkg`
            : "Loading…"}
        </span>
      </div>
      {placementQuery.data && Number(placementQuery.data.unplaced_weight_kg) <= 0 && (
        <p className="mt-1 text-xs text-ink-muted">
          This Lot has no unplaced balance -- release it from Cold Storage before dispatching.
        </p>
      )}
      <div className="mt-2 grid grid-cols-1 gap-3 sm:grid-cols-2">
        <label className="flex flex-col gap-1">
          <span className={labelClass}>Dispatched weight (kg)</span>
          <input
            type="number" min={0.001} step={0.001} className={inputClass}
            {...register(`lines.${index}.dispatched_weight_kg`, { valueAsNumber: true })}
          />
          {rowErrors?.dispatched_weight_kg && <span className={errorClass}>{rowErrors.dispatched_weight_kg.message}</span>}
        </label>
        <label className="flex flex-col gap-1">
          <span className={labelClass}>Dispatched package count</span>
          <input
            type="number" min={1} step={1} className={inputClass}
            {...register(`lines.${index}.dispatched_package_count`, { valueAsNumber: true })}
          />
          {rowErrors?.dispatched_package_count && (
            <span className={errorClass}>{rowErrors.dispatched_package_count.message}</span>
          )}
        </label>
      </div>
    </li>
  );
}
