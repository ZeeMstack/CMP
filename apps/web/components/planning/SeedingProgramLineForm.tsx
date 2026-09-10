"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { useForm } from "react-hook-form";

import { Button } from "@/components/ui/Button";
import type { SeedingProgramLineCreate } from "@/lib/api/client";
import { useUoms, useVarieties } from "@/lib/query/hooks";
import {
  DEFAULT_SEEDING_PROGRAM_LINE_FORM_VALUES,
  buildSeedingProgramLineCreatePayload,
  seedingProgramLineFormSchema,
  type SeedingProgramLineFormValues,
} from "@/lib/validation/planning";

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

export function SeedingProgramLineForm({
  cropId,
  cropName,
  expectedCoverageUomId,
  expectedCoverageUomCode,
  onSubmit,
  isSubmitting,
  serverError,
}: {
  cropId: string;
  cropName: string;
  expectedCoverageUomId: string;
  expectedCoverageUomCode: string;
  onSubmit: (payload: SeedingProgramLineCreate) => void;
  isSubmitting: boolean;
  serverError?: string | null;
}) {
  const {
    register, handleSubmit, formState: { errors },
  } = useForm<SeedingProgramLineFormValues>({
    resolver: zodResolver(seedingProgramLineFormSchema),
    defaultValues: DEFAULT_SEEDING_PROGRAM_LINE_FORM_VALUES,
    mode: "onBlur",
  });

  const varietiesQuery = useVarieties(cropId);
  const uomsQuery = useUoms();
  const countUoms = uomsQuery.data?.filter((uom) => uom.quantity_kind === "count") ?? [];
  const [clientCommandId] = useState(() => crypto.randomUUID());

  function submit(values: SeedingProgramLineFormValues) {
    onSubmit(buildSeedingProgramLineCreatePayload(values, clientCommandId, cropId, expectedCoverageUomId));
  }

  return (
    <form onSubmit={handleSubmit(submit)} className="flex max-w-2xl flex-col gap-6">
      <p className="text-xs text-ink-muted">
        A plan line is planning intent only — it does not create a Crop Batch or reserve seed. This line fulfils{" "}
        {cropName}&apos;s demand; expected coverage is always expressed in {expectedCoverageUomCode}, the same unit
        as the requirement.
      </p>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <Field label="Variety (optional)">
          <select {...register("variety_id")} className={inputClass}>
            <option value="">Any variety</option>
            {varietiesQuery.data?.map((variety) => (
              <option key={variety.id} value={variety.id}>
                {variety.name}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Planned sow date" error={errors.planned_sow_date?.message}>
          <input type="date" {...register("planned_sow_date")} className={inputClass} />
        </Field>
        <div className="grid grid-cols-2 gap-2">
          <Field label="Planned sowing quantity" error={errors.planned_quantity?.message}>
            <input inputMode="decimal" {...register("planned_quantity")} className={inputClass} placeholder="20000" />
          </Field>
          <Field label="Unit" error={errors.planned_quantity_uom_id?.message}>
            <select {...register("planned_quantity_uom_id")} className={inputClass}>
              <option value="">Select…</option>
              {countUoms.map((uom) => (
                <option key={uom.id} value={uom.id}>
                  {uom.code}
                </option>
              ))}
            </select>
          </Field>
        </div>
        <Field label={`Expected coverage (${expectedCoverageUomCode})`} error={errors.expected_coverage_quantity?.message}>
          <input
            inputMode="decimal"
            {...register("expected_coverage_quantity")}
            className={inputClass}
            placeholder="10000"
          />
        </Field>
        <Field label="Notes (optional)" error={errors.notes?.message}>
          <input {...register("notes")} className={inputClass} />
        </Field>
      </div>

      {serverError && <p role="alert" className={errorClass}>{serverError}</p>}

      <div>
        <Button type="submit" variant="primary" disabled={isSubmitting}>
          {isSubmitting ? "Saving…" : "Add plan line"}
        </Button>
      </div>
    </form>
  );
}
