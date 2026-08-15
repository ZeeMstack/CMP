"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useMemo, useState } from "react";
import { Controller, useFieldArray, useForm } from "react-hook-form";

import type { SowNewBatchCreate } from "@/lib/api/client";
import { useAssets, useAvailableSeedTrays, useGreenhouseSetupOverview, useGreenhouseStructure, useSeedLots } from "@/lib/query/hooks";
import {
  DEFAULT_SOWING_FORM_VALUES,
  buildSowingPayload,
  sowingFormSchema,
  totalSeedsSown,
  type SowingFormValues,
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

function nowDateAndTime() {
  const now = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  return {
    date: `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`,
    time: `${pad(now.getHours())}:${pad(now.getMinutes())}`,
  };
}

export function SowingForm({
  farmId, onSubmit, isSubmitting, serverError,
}: {
  farmId: string;
  onSubmit: (payload: SowNewBatchCreate) => void;
  isSubmitting: boolean;
  serverError?: string | null;
}) {
  const [step, setStep] = useState<"configure" | "review">("configure");
  const [clientCommandId] = useState(() => crypto.randomUUID());
  const [nurseryGreenhouseId, setNurseryGreenhouseId] = useState("");

  const initial = nowDateAndTime();
  const {
    register, control, watch, setValue, trigger, getValues, formState: { errors },
  } = useForm<SowingFormValues>({
    resolver: zodResolver(sowingFormSchema),
    defaultValues: { ...DEFAULT_SOWING_FORM_VALUES, effective_date: initial.date, effective_time_of_day: initial.time },
    mode: "onBlur",
  });
  const { fields, append, remove } = useFieldArray({ control, name: "trays" });

  const overviewQuery = useGreenhouseSetupOverview(farmId);
  const nurseries = useMemo(
    () => (overviewQuery.data ?? []).filter((item) => item.classification === "nursery"),
    [overviewQuery.data],
  );
  const structureQuery = useGreenhouseStructure(farmId, nurseryGreenhouseId || "__none__");
  const seedingStations = nurseryGreenhouseId ? (structureQuery.data?.nursery_seeding_stations ?? []) : [];

  const seedLotsQuery = useSeedLots(farmId);
  const seedingMachinesQuery = useAssets(farmId, "seeding_machine");
  const availableTraysQuery = useAvailableSeedTrays(farmId);

  const selectedTrayIds = new Set(watch("trays").map((t) => t.carrier_id));
  const selectableTrays = (availableTraysQuery.data ?? []).filter((t) => !selectedTrayIds.has(t.id));

  async function goToReview() {
    const valid = await trigger();
    if (valid) setStep("review");
  }

  function submitReview() {
    onSubmit(buildSowingPayload(getValues(), clientCommandId));
  }

  if (step === "review") {
    const values = getValues();
    const seedLot = seedLotsQuery.data?.find((l) => l.id === values.seed_lot_id);
    const selectedSeedingStation = seedingStations.find((s) => s.id === values.seeding_station_id);
    const machine = seedingMachinesQuery.data?.find((m) => m.id === values.seeding_machine_id);
    const total = totalSeedsSown(values.trays);
    return (
      <div className="flex flex-col gap-4">
        <div className="flex flex-col gap-4 rounded-lg border border-border-subtle bg-surface p-4">
          <h2 className="text-sm font-semibold text-ink">Review before sowing</h2>
          <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm sm:grid-cols-3">
            <div>
              <dt className="text-ink-muted">Batch code</dt>
              <dd className="font-medium text-ink">generated on save</dd>
            </div>
            <div>
              <dt className="text-ink-muted">Seeding Station</dt>
              <dd className="font-medium text-ink">{selectedSeedingStation?.code ?? "—"}</dd>
            </div>
            <div>
              <dt className="text-ink-muted">Seed Lot</dt>
              <dd className="font-medium text-ink">{seedLot?.code ?? "—"}</dd>
            </div>
            {seedLot && (
              <>
                <div>
                  <dt className="text-ink-muted">Crop</dt>
                  <dd className="font-medium text-ink">{seedLot.crop.common_name}</dd>
                </div>
                <div>
                  <dt className="text-ink-muted">Variety</dt>
                  <dd className="font-medium text-ink">{seedLot.variety.name}</dd>
                </div>
              </>
            )}
            {machine && (
              <div>
                <dt className="text-ink-muted">Seeding Machine</dt>
                <dd className="font-medium text-ink">{machine.code} (farm-level equipment)</dd>
              </div>
            )}
            <div>
              <dt className="text-ink-muted">Occurred at</dt>
              <dd className="font-medium text-ink">
                {values.effective_date} {values.effective_time_of_day}
              </dd>
            </div>
            <div>
              <dt className="text-ink-muted">Trays</dt>
              <dd className="font-medium text-ink">{values.trays.length}</dd>
            </div>
            <div>
              <dt className="text-ink-muted">Total seeds sown</dt>
              <dd className="font-medium text-ink">{total.toLocaleString()}</dd>
            </div>
          </dl>
          <ul className="divide-y divide-border-subtle text-sm">
            {values.trays.map((tray) => (
              <li key={tray.carrier_id} className="flex items-center justify-between py-1.5">
                <span className="text-ink">{tray.code}</span>
                <span className="text-ink-muted">{tray.seeds_sown} seeds</span>
              </li>
            ))}
          </ul>
        </div>
        {serverError && <p role="alert" className={errorClass}>{serverError}</p>}
        <div className="flex gap-3">
          <button
            type="button"
            onClick={() => setStep("configure")}
            disabled={isSubmitting}
            className="min-h-11 rounded-md border border-border-subtle px-4 text-sm font-medium text-ink hover:bg-surface-subtle"
          >
            Back
          </button>
          <button
            type="button"
            onClick={submitReview}
            disabled={isSubmitting}
            className="min-h-11 rounded-md bg-brand-700 px-4 text-sm font-medium text-white hover:bg-brand-800 disabled:opacity-60"
          >
            {isSubmitting ? "Sowing…" : "Sow"}
          </button>
        </div>
      </div>
    );
  }

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        goToReview();
      }}
      className="flex flex-col gap-6"
    >
      <fieldset className="flex flex-col gap-4 rounded-lg border border-border-subtle p-4">
        <legend className="px-1 text-sm font-semibold text-ink">Nursery / Seeding Station</legend>
        <Field label="Nursery">
          <select
            value={nurseryGreenhouseId}
            onChange={(e) => {
              setNurseryGreenhouseId(e.target.value);
              setValue("seeding_station_id", "");
            }}
            className={inputClass}
          >
            <option value="">Select a Nursery…</option>
            {nurseries.map((n) => (
              <option key={n.greenhouse_id} value={n.greenhouse_id}>
                {n.code}
              </option>
            ))}
          </select>
        </Field>
        <Controller
          name="seeding_station_id"
          control={control}
          render={({ field }) => {
            // Auto-select only when exactly one Seeding Station exists for
            // this Nursery -- with zero, there is nothing to select
            // (an actionable configuration message below); with more than
            // one, the operator must choose explicitly (never guessed).
            if (nurseryGreenhouseId && seedingStations.length === 1 && field.value !== seedingStations[0].id) {
              field.onChange(seedingStations[0].id);
            }
            if (seedingStations.length > 1) {
              return (
                <Field label="Seeding Station" error={errors.seeding_station_id?.message}>
                  <select
                    value={field.value}
                    onChange={(e) => field.onChange(e.target.value)}
                    className={inputClass}
                  >
                    <option value="">Select a Seeding Station…</option>
                    {seedingStations.map((station) => (
                      <option key={station.id} value={station.id}>
                        {station.code}
                      </option>
                    ))}
                  </select>
                </Field>
              );
            }
            return (
              <Field label="Seeding Station" error={errors.seeding_station_id?.message}>
                <input
                  className={inputClass}
                  readOnly
                  value={
                    !nurseryGreenhouseId
                      ? ""
                      : structureQuery.isLoading
                        ? "Loading…"
                        : seedingStations.length === 1
                          ? seedingStations[0].code
                          : "This Nursery has no Seeding Station configured"
                  }
                  placeholder="Select a Nursery first"
                />
              </Field>
            );
          }}
        />
      </fieldset>

      <fieldset className="flex flex-col gap-4 rounded-lg border border-border-subtle p-4">
        <legend className="px-1 text-sm font-semibold text-ink">Seed Lot</legend>
        <Field label="Seed Lot" error={errors.seed_lot_id?.message}>
          <select {...register("seed_lot_id")} className={inputClass}>
            <option value="">Select a Seed Lot…</option>
            {seedLotsQuery.data?.map((lot) => (
              <option key={lot.id} value={lot.id}>
                {lot.code} — {lot.crop.common_name} / {lot.variety.name}
              </option>
            ))}
          </select>
        </Field>
      </fieldset>

      <fieldset className="flex flex-col gap-4 rounded-lg border border-border-subtle p-4">
        <legend className="px-1 text-sm font-semibold text-ink">Seeding Machine (optional)</legend>
        <p className="text-xs text-ink-muted">Farm-level equipment — recorded as provenance only.</p>
        <Field label="Seeding Machine">
          <select {...register("seeding_machine_id")} className={inputClass}>
            <option value="">None</option>
            {seedingMachinesQuery.data?.map((machine) => (
              <option key={machine.id} value={machine.id}>
                {machine.code}
              </option>
            ))}
          </select>
        </Field>
      </fieldset>

      <fieldset className="grid grid-cols-1 gap-4 rounded-lg border border-border-subtle p-4 sm:grid-cols-2">
        <legend className="px-1 text-sm font-semibold text-ink">Sowing date/time</legend>
        <Field label="Date" error={errors.effective_date?.message}>
          <input type="date" {...register("effective_date")} className={inputClass} />
        </Field>
        <Field label="Time" error={errors.effective_time_of_day?.message}>
          <input type="time" {...register("effective_time_of_day")} className={inputClass} />
        </Field>
      </fieldset>

      <fieldset className="flex flex-col gap-4 rounded-lg border border-border-subtle p-4">
        <legend className="px-1 text-sm font-semibold text-ink">Seed Trays</legend>
        {errors.trays?.message && <p className={errorClass}>{errors.trays.message}</p>}
        <Field label="Add a Seed Tray">
          <select
            className={inputClass}
            value=""
            onChange={(e) => {
              const tray = selectableTrays.find((t) => t.id === e.target.value);
              if (tray) append({ carrier_id: tray.id, code: tray.code, seeds_sown: 0 });
            }}
          >
            <option value="">Select an available Seed Tray…</option>
            {selectableTrays.map((tray) => (
              <option key={tray.id} value={tray.id}>
                {tray.code}
              </option>
            ))}
          </select>
        </Field>
        {fields.length > 0 && (
          <ul className="divide-y divide-border-subtle">
            {fields.map((field, index) => (
              <li key={field.id} className="flex items-center gap-3 py-2">
                <span className="min-w-24 text-sm font-medium text-ink">{field.code}</span>
                <div className="flex-1">
                  <input
                    type="number"
                    {...register(`trays.${index}.seeds_sown`, { valueAsNumber: true })}
                    className={inputClass}
                    placeholder="Seeds sown"
                    aria-label={`Seeds sown for ${field.code}`}
                  />
                  {errors.trays?.[index]?.seeds_sown && (
                    <span className={errorClass}>{errors.trays[index]?.seeds_sown?.message}</span>
                  )}
                </div>
                <button
                  type="button"
                  onClick={() => remove(index)}
                  className="min-h-11 rounded-md border border-border-subtle px-3 text-xs font-medium text-ink hover:bg-surface-subtle"
                >
                  Remove
                </button>
              </li>
            ))}
          </ul>
        )}
        {fields.length > 0 && (
          <p className="text-sm text-ink-muted">
            {fields.length} {fields.length === 1 ? "tray" : "trays"} selected · {totalSeedsSown(watch("trays"))} total
            seeds sown
          </p>
        )}
      </fieldset>

      <fieldset className="flex flex-col gap-4 rounded-lg border border-border-subtle p-4">
        <legend className="px-1 text-sm font-semibold text-ink">Note (optional)</legend>
        <textarea {...register("note")} className={`${inputClass} min-h-20`} rows={2} />
      </fieldset>

      <div>
        <button
          type="submit"
          className="min-h-11 rounded-md bg-brand-700 px-4 text-sm font-medium text-white hover:bg-brand-800"
        >
          Review
        </button>
      </div>
    </form>
  );
}
