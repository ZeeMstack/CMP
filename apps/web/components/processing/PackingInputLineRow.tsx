"use client";

import { useEffect, useRef } from "react";
import type { FieldErrors, UseFormRegister, UseFormSetValue, UseFormWatch } from "react-hook-form";

import type { GradedProduceLotRead } from "@/lib/api/client";
import { useGradedProduceLotBalance } from "@/lib/query/hooks";
import type { RecordPackingFormValues } from "@/lib/validation/packing";

const inputClass =
  "min-h-11 w-full rounded-md border border-border-subtle bg-surface px-3 text-sm text-ink focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-600";
const labelClass = "block text-xs font-medium text-ink-muted";
const errorClass = "text-xs text-red-700";

/** POSTHARVEST-OPS-001G: one Graded Produce Lot input line inside the
 * Packing form. Fetches this Lot's own live balance (own component instance
 * per line, same rationale as `GradingOutputRow`'s per-row cascade) and
 * seeds `consumed_weight_kg`/`available_weight_kg` from it exactly once
 * when the balance first arrives -- a `hasSeeded` ref, not a dependency on
 * the operator's own edits, so typing a smaller consumed amount is never
 * clobbered by a later re-render. */
export function PackingInputLineRow({
  farmId,
  lot,
  index,
  register,
  setValue,
  watch,
  errors,
  onRemove,
  removable,
}: {
  farmId: string;
  lot: GradedProduceLotRead;
  index: number;
  register: UseFormRegister<RecordPackingFormValues>;
  setValue: UseFormSetValue<RecordPackingFormValues>;
  watch: UseFormWatch<RecordPackingFormValues>;
  errors: FieldErrors<RecordPackingFormValues>;
  onRemove: () => void;
  removable: boolean;
}) {
  const balanceQuery = useGradedProduceLotBalance(farmId, lot.id);
  const hasSeeded = useRef(false);
  const countMode = watch("count_mode");
  const rowErrors = errors.input_lines?.[index];

  useEffect(() => {
    if (hasSeeded.current || !balanceQuery.data) return;
    hasSeeded.current = true;
    setValue(`input_lines.${index}.available_weight_kg`, Number(balanceQuery.data.available_weight_kg));
    setValue(`input_lines.${index}.available_whole_unit_count`, balanceQuery.data.available_whole_unit_count);
    setValue(`input_lines.${index}.consumed_weight_kg`, Number(balanceQuery.data.available_weight_kg));
    if (balanceQuery.data.available_whole_unit_count != null) {
      setValue(`input_lines.${index}.consumed_whole_unit_count`, balanceQuery.data.available_whole_unit_count);
    }
  }, [balanceQuery.data, index, setValue]);

  return (
    <li className="rounded-md border border-border-subtle p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="text-sm font-semibold text-ink">{lot.code}</span>
        <span className="text-xs text-ink-muted">
          Available{" "}
          {balanceQuery.data
            ? `${balanceQuery.data.available_weight_kg} kg${
                countMode ? ` / ${balanceQuery.data.available_whole_unit_count} units` : ""
              }`
            : "Loading…"}
        </span>
      </div>
      <div className="mt-2 grid grid-cols-1 gap-3 sm:grid-cols-3">
        <label className="flex flex-col gap-1">
          <span className={labelClass}>Consumed weight (kg)</span>
          <input
            type="number" min={0.001} step={0.001} className={inputClass}
            {...register(`input_lines.${index}.consumed_weight_kg`, { valueAsNumber: true })}
          />
          {rowErrors?.consumed_weight_kg && <span className={errorClass}>{rowErrors.consumed_weight_kg.message}</span>}
        </label>
        {countMode && (
          <label className="flex flex-col gap-1">
            <span className={labelClass}>Consumed count</span>
            <input
              type="number" min={1} step={1} className={inputClass}
              {...register(`input_lines.${index}.consumed_whole_unit_count`, { valueAsNumber: true })}
            />
            {rowErrors?.consumed_whole_unit_count && (
              <span className={errorClass}>{rowErrors.consumed_whole_unit_count.message}</span>
            )}
          </label>
        )}
        <label className="flex flex-col gap-1">
          <span className={labelClass}>Note (optional)</span>
          <input className={inputClass} {...register(`input_lines.${index}.note`)} />
        </label>
      </div>
      {removable && (
        <button
          type="button"
          onClick={onRemove}
          className="mt-2 min-h-11 rounded-md border border-border-subtle px-3 text-xs font-medium text-ink hover:bg-surface-subtle"
        >
          Remove Lot
        </button>
      )}
    </li>
  );
}
