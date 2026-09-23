"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { useForm } from "react-hook-form";

import { Button } from "@/components/ui/Button";
import type { SeedLotCreate } from "@/lib/api/client";
import { useCrops, useVarieties } from "@/lib/query/hooks";
import {
  DEFAULT_SEED_LOT_FORM_VALUES,
  buildSeedLotPayload,
  seedLotFormSchema,
  type SeedLotFormValues,
} from "@/lib/validation/nursery";

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

/** UX-OPS-001B §6.4: a compact guided command, not a two-step Review flow
 * (this is a simple reference-data command, and the ticket explicitly says
 * not to add a redundant Review step for one). Required identity (Crop,
 * Variety, Supplier lot code) stays up front; supplier/date facts that are
 * genuinely optional collapse behind a secondary disclosure so they never
 * compete visually with the required fields. Payload/validation/submit
 * behavior is otherwise byte-for-byte unchanged from the prior form. */
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
  const [showMoreDetails, setShowMoreDetails] = useState(false);

  const cropsQuery = useCrops();
  const cropId = watch("crop_id");
  const varietiesQuery = useVarieties(cropId || undefined);

  function submit(values: SeedLotFormValues) {
    onSubmit(buildSeedLotPayload(values));
  }

  return (
    <form onSubmit={handleSubmit(submit)} className="flex max-w-2xl flex-col gap-5">
      <p className="text-xs text-wl-text-secondary">
        A Seed Lot is a traceability source for the seed used to sow a batch — not a stock-on-hand record. CMP
        does not track quantity received or remaining here.
      </p>

      <div className="flex flex-col gap-4 rounded-xl border border-wl-border bg-wl-surface-raised p-4">
        <h2 className="text-xs font-semibold uppercase tracking-wide text-wl-text-secondary">Identity</h2>
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
        </div>
      </div>

      <button
        type="button"
        onClick={() => setShowMoreDetails((v) => !v)}
        className="self-start text-sm font-medium text-wl-brand hover:underline"
      >
        {showMoreDetails ? "Hide more details" : "More details (optional)"}
      </button>

      {showMoreDetails && (
        <div className="grid grid-cols-1 gap-4 rounded-xl border border-wl-border bg-wl-surface-sunken p-4 sm:grid-cols-2">
          <Field label="Supplier name">
            <input {...register("supplier_name")} className={inputClass} placeholder="Rijk Zwaan" />
          </Field>
          <Field label="Supplier lot reference">
            <input {...register("supplier_lot_reference")} className={inputClass} />
          </Field>
          <Field label="Received date">
            <input type="date" {...register("received_date")} className={inputClass} />
          </Field>
          <Field label="Expiry date">
            <input type="date" {...register("expiry_date")} className={inputClass} />
          </Field>
        </div>
      )}

      {serverError && <p role="alert" className={errorClass}>{serverError}</p>}

      <div>
        <Button type="submit" variant="primary" disabled={isSubmitting}>
          {isSubmitting ? "Saving…" : "Save Seed Lot"}
        </Button>
      </div>
    </form>
  );
}
