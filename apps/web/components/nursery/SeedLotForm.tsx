"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";

import type { SeedLotCreate } from "@/lib/api/client";
import { useCrops, useVarieties } from "@/lib/query/hooks";
import {
  DEFAULT_SEED_LOT_FORM_VALUES,
  buildSeedLotPayload,
  seedLotFormSchema,
  type SeedLotFormValues,
} from "@/lib/validation/nursery";

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

export function SeedLotForm({
  onSubmit, isSubmitting, serverError,
}: {
  onSubmit: (payload: SeedLotCreate) => void;
  isSubmitting: boolean;
  serverError?: string | null;
}) {
  const {
    register, watch, handleSubmit, formState: { errors },
  } = useForm<SeedLotFormValues>({
    resolver: zodResolver(seedLotFormSchema),
    defaultValues: DEFAULT_SEED_LOT_FORM_VALUES,
    mode: "onBlur",
  });

  const cropsQuery = useCrops();
  const cropId = watch("crop_id");
  const varietiesQuery = useVarieties(cropId || undefined);

  function submit(values: SeedLotFormValues) {
    onSubmit(buildSeedLotPayload(values));
  }

  return (
    <form onSubmit={handleSubmit(submit)} className="flex flex-col gap-6">
      <p className="text-xs text-ink-muted">
        A Seed Lot is a traceability source for the seed used to sow a batch — not a stock-on-hand record. CMP
        does not track quantity received or remaining here.
      </p>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <Field label="Crop" error={errors.crop_id?.message}>
          <select {...register("crop_id")} className={inputClass}>
            <option value="">Select a crop…</option>
            {cropsQuery.data?.map((crop) => (
              <option key={crop.id} value={crop.id}>
                {crop.common_name}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Variety" error={errors.variety_id?.message}>
          <select {...register("variety_id")} className={inputClass} disabled={!cropId}>
            <option value="">{cropId ? "Select a variety…" : "Select a crop first"}</option>
            {varietiesQuery.data?.map((variety) => (
              <option key={variety.id} value={variety.id}>
                {variety.name}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Supplier lot code" error={errors.code?.message}>
          <input {...register("code")} className={inputClass} placeholder="RZ-MAM-2026-001" />
        </Field>
        <Field label="Supplier name (optional)">
          <input {...register("supplier_name")} className={inputClass} placeholder="Rijk Zwaan" />
        </Field>
        <Field label="Supplier lot reference (optional)">
          <input {...register("supplier_lot_reference")} className={inputClass} />
        </Field>
        <Field label="Received date (optional)">
          <input type="date" {...register("received_date")} className={inputClass} />
        </Field>
        <Field label="Expiry date (optional)">
          <input type="date" {...register("expiry_date")} className={inputClass} />
        </Field>
      </div>

      {serverError && <p role="alert" className={errorClass}>{serverError}</p>}

      <div>
        <button
          type="submit"
          disabled={isSubmitting}
          className="min-h-11 rounded-md bg-brand-700 px-4 text-sm font-medium text-white hover:bg-brand-800 disabled:opacity-60"
        >
          {isSubmitting ? "Saving…" : "Save Seed Lot"}
        </button>
      </div>
    </form>
  );
}
