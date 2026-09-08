"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useEffect, useMemo, useState } from "react";
import { useForm, useWatch } from "react-hook-form";

import { FilterableSelect, type FilterableSelectOption } from "@/components/FilterableSelect";
import type { VinesProductionTransferCreate } from "@/lib/api/client";
import { AppError, friendlyMutationErrorMessage } from "@/lib/errors/adapter";
import { useAvailableGrowBagPools, useGreenhouseSetupOverview, useGreenhouseStructure, useIntervinesPlacements } from "@/lib/query/hooks";
import {
  DEFAULT_VINES_PRODUCTION_TRANSFER_FORM_VALUES,
  buildVinesProductionTransferPayload,
  vinesProductionTransferFormSchema,
  type VinesProductionTransferFormValues,
} from "@/lib/validation/vinesProductionTransfer";

const inputClassBase =
  "min-h-11 rounded-md border border-border-subtle bg-surface px-3 text-sm text-ink focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-600";
const inputClass = `${inputClassBase} w-full`;
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

/** VINES-OPS-001B: the Vines Production Transfer compact operator workspace
 * -- one InterVines (Batch, Table) source group, a plant count, one
 * destination Greenhouse/Grow Gutter, and a Grow Bag specification -- the
 * server allocates the actual Grow Cubes (source, retained), Grow Bags, and
 * Grow Bag Positions. One transaction workspace (configure -> review ->
 * confirm), matching `IntervinesTransplantForm`'s own established pattern. */
export function VinesProductionTransferForm({
  farmId,
  onSubmit,
  isSubmitting,
  serverError,
}: {
  farmId: string;
  onSubmit: (batchId: string, payload: VinesProductionTransferCreate, gutterCode: string) => void;
  isSubmitting: boolean;
  serverError?: AppError | null;
}) {
  const [step, setStep] = useState<"configure" | "review">("configure");
  const [clientCommandId, setClientCommandId] = useState(() => crypto.randomUUID());
  const [lastSubmittedFingerprint, setLastSubmittedFingerprint] = useState<string | null>(null);

  const initial = nowDateAndTime();
  const {
    register, control, setValue, getValues, trigger, formState: { errors },
  } = useForm<VinesProductionTransferFormValues>({
    resolver: zodResolver(vinesProductionTransferFormSchema),
    defaultValues: {
      ...DEFAULT_VINES_PRODUCTION_TRANSFER_FORM_VALUES,
      effective_date: initial.date,
      effective_time_of_day: initial.time,
    },
    mode: "onBlur",
  });
  const values = useWatch({ control }) as VinesProductionTransferFormValues;

  const intervinesQuery = useIntervinesPlacements(farmId);
  const overviewQuery = useGreenhouseSetupOverview(farmId);
  const vinesGreenhouses = useMemo(
    () => (overviewQuery.data ?? []).filter((item) => item.classification === "vines"),
    [overviewQuery.data],
  );

  const [prevServerError, setPrevServerError] = useState(serverError);
  if (serverError !== prevServerError) {
    setPrevServerError(serverError);
    if (serverError?.kind === "conflict") setStep("configure");
  }

  const structureQuery = useGreenhouseStructure(farmId, values.destination_greenhouse_id || "__none__");
  const gutterOptions: FilterableSelectOption[] = useMemo(() => {
    if (!values.destination_greenhouse_id) return [];
    const zones = structureQuery.data?.vines_zones ?? [];
    return zones.flatMap((zone) =>
      zone.spans.flatMap((span) =>
        span.gutters.map((gutter) => ({
          value: gutter.id, label: gutter.code, description: `${gutter.bag_position_count} Bag positions`,
        })),
      ),
    );
  }, [values.destination_greenhouse_id, structureQuery.data]);

  const growBagPoolsQuery = useAvailableGrowBagPools(farmId, values.destination_grow_gutter_id || undefined);
  const growBagPools = useMemo(() => growBagPoolsQuery.data ?? [], [growBagPoolsQuery.data]);
  const showSpecificationPicker = growBagPools.length > 1;
  const specificationOptions: FilterableSelectOption[] = useMemo(
    () =>
      growBagPools.map((p) => ({
        value: p.specification_id, label: p.specification.code,
        description: `${p.available_plant_capacity.toLocaleString()} plants available`,
      })),
    [growBagPools],
  );
  const selectedPool = growBagPools.find((p) => p.specification_id === values.grow_bag_specification_id);
  const availablePlantCapacity = selectedPool
    ? selectedPool.available_plant_capacity
    : (growBagPools.length === 1 ? growBagPools[0].available_plant_capacity : 0);

  useEffect(() => {
    setValue("available_plant_capacity", availablePlantCapacity);
  }, [availablePlantCapacity, setValue]);

  // Exactly one Grow Bag specification pool -> auto-select it, no picker
  // shown (ticket: the picker only appears "if relevant").
  useEffect(() => {
    if (growBagPools.length === 1 && !values.grow_bag_specification_id) {
      setValue("grow_bag_specification_id", growBagPools[0].specification_id);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [growBagPools]);

  const intervinesRows = useMemo(() => intervinesQuery.data ?? [], [intervinesQuery.data]);
  const sourceOptions: FilterableSelectOption[] = useMemo(
    () =>
      intervinesRows.map((row) => ({
        value: row.table_id, label: row.table_code,
        description: `${row.batch_code} — ${row.plant_count.toLocaleString()} available`,
      })),
    [intervinesRows],
  );

  function selectSource(tableId: string) {
    const row = intervinesRows.find((r) => r.table_id === tableId);
    if (!row) return;
    setValue("source_intervines_table_id", tableId, { shouldValidate: true });
    setValue("source_table_code", row.table_code);
    setValue("current_available", row.plant_count, { shouldValidate: true });
    setValue("batch_id", row.batch_id);
    setValue("batch_code", row.batch_code);
    setValue("crop_common_name", row.crop_common_name);
    setValue("variety_name", row.variety_name ?? "");
  }

  async function goToReview() {
    // `available_plant_capacity` is normally kept in sync by the effect
    // above, but that effect can still lag one render behind this handler
    // (e.g. the Grow Bag pool query resolving in the same tick as a fast
    // sequence of field changes) -- writing it synchronously here, from the
    // SAME render closure the on-screen "Available capacity" figure was
    // just derived from, guarantees validation checks exactly what the
    // operator saw before clicking, never a stale effect-synced value.
    setValue("available_plant_capacity", availablePlantCapacity);
    const valid = await trigger();
    if (valid) setStep("review");
  }

  function submitReview() {
    const finalValues = getValues();
    const gutter = gutterOptions.find((g) => g.value === finalValues.destination_grow_gutter_id);
    const payload = buildVinesProductionTransferPayload(finalValues, clientCommandId);
    // eslint-disable-next-line @typescript-eslint/no-unused-vars -- rest-destructure to omit the key, not to use it
    const { client_command_id: _omit, ...fingerprint } = payload;
    const fingerprintJson = JSON.stringify(fingerprint);
    let idToUse = clientCommandId;
    if (lastSubmittedFingerprint !== null && lastSubmittedFingerprint !== fingerprintJson) {
      idToUse = crypto.randomUUID();
      setClientCommandId(idToUse);
    }
    setLastSubmittedFingerprint(fingerprintJson);
    onSubmit(finalValues.batch_id, { ...payload, client_command_id: idToUse }, gutter?.label ?? finalValues.gutter_code);
  }

  if (step === "review") {
    const reviewValues = getValues();
    const gutter = gutterOptions.find((g) => g.value === reviewValues.destination_grow_gutter_id);
    return (
      <div className="flex flex-col gap-4">
        <div className="flex flex-col gap-4 rounded-xl border border-border-subtle bg-surface p-4">
          <h2 className="font-serif text-base font-semibold text-ink">Review before transferring</h2>
          <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm sm:grid-cols-3">
            <div>
              <dt className="text-ink-muted">Batch</dt>
              <dd className="font-medium text-ink">{reviewValues.batch_code}</dd>
            </div>
            <div>
              <dt className="text-ink-muted">Plants</dt>
              <dd className="font-medium text-ink">{reviewValues.plant_count.toLocaleString()}</dd>
            </div>
            <div>
              <dt className="text-ink-muted">Grow Cubes retained</dt>
              <dd className="font-medium text-ink">{reviewValues.plant_count.toLocaleString()}</dd>
            </div>
            <div>
              <dt className="text-ink-muted">Grow Gutter</dt>
              <dd className="font-medium text-ink">{gutter?.label ?? reviewValues.gutter_code}</dd>
            </div>
          </dl>
        </div>
        {serverError && (
          <p role="alert" className={errorClass}>
            {friendlyMutationErrorMessage(serverError)}
          </p>
        )}
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
            {isSubmitting ? "Transferring…" : "Confirm transfer"}
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
      <fieldset className="flex flex-col gap-4 rounded-xl border border-border-subtle bg-surface p-4">
        <legend className="px-1 text-sm font-semibold text-ink">Source</legend>
        <Field label="Batch / InterVines Table" error={errors.source_intervines_table_id?.message}>
          <FilterableSelect
            aria-label="Batch / InterVines Table"
            options={sourceOptions}
            loading={intervinesQuery.isLoading}
            value={values.source_intervines_table_id}
            placeholder="Search InterVines Table by code…"
            emptyMessage="No InterVines sources available"
            onChange={selectSource}
          />
        </Field>
        {values.source_intervines_table_id && (
          <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm sm:grid-cols-3">
            <div>
              <dt className="text-ink-muted">Batch</dt>
              <dd className="font-medium text-ink">{values.batch_code}</dd>
            </div>
            <div>
              <dt className="text-ink-muted">Crop / Variety</dt>
              <dd className="font-medium text-ink">
                {values.crop_common_name}
                {values.variety_name ? ` / ${values.variety_name}` : ""}
              </dd>
            </div>
            <div>
              <dt className="text-ink-muted">Available plants</dt>
              <dd className="font-medium text-ink">{values.current_available.toLocaleString()}</dd>
            </div>
          </dl>
        )}
      </fieldset>

      {values.source_intervines_table_id && (
        <fieldset className="flex flex-col gap-4 rounded-xl border border-border-subtle bg-surface p-4">
          <legend className="px-1 text-sm font-semibold text-ink">Destination</legend>
          {vinesGreenhouses.length > 1 && (
            <Field label="Destination Greenhouse">
              <select
                value={values.destination_greenhouse_id}
                onChange={(e) => {
                  setValue("destination_greenhouse_id", e.target.value);
                  setValue("destination_grow_gutter_id", "");
                  setValue("gutter_code", "");
                }}
                className={inputClass}
              >
                <option value="">Select a Greenhouse…</option>
                {vinesGreenhouses.map((gh) => (
                  <option key={gh.greenhouse_id} value={gh.greenhouse_id}>
                    {gh.code}
                  </option>
                ))}
              </select>
            </Field>
          )}
          {vinesGreenhouses.length === 1 && values.destination_greenhouse_id !== vinesGreenhouses[0].greenhouse_id && (
            <SingleGreenhouseAutoSelect greenhouseId={vinesGreenhouses[0].greenhouse_id} setValue={setValue} />
          )}

          {values.destination_greenhouse_id && (
            <Field label="Grow Gutter" error={errors.destination_grow_gutter_id?.message}>
              <FilterableSelect
                aria-label="Grow Gutter"
                options={gutterOptions}
                loading={structureQuery.isLoading}
                value={values.destination_grow_gutter_id}
                placeholder="Search Gutter by code…"
                emptyMessage="No Grow Gutters configured in this Greenhouse"
                onChange={(gutterId) => {
                  const gutter = gutterOptions.find((g) => g.value === gutterId);
                  setValue("destination_grow_gutter_id", gutterId, { shouldValidate: true });
                  setValue("gutter_code", gutter?.label ?? "");
                }}
              />
            </Field>
          )}

          {values.destination_grow_gutter_id && (
            <>
              <Field label="Plants to transfer" error={errors.plant_count?.message}>
                <input
                  type="number" min={1} step={1} className={`${inputClassBase} w-full sm:w-40`}
                  {...register("plant_count", { valueAsNumber: true })}
                />
              </Field>

              {showSpecificationPicker && (
                <Field label="Grow Bag specification" error={errors.grow_bag_specification_id?.message}>
                  <FilterableSelect
                    aria-label="Grow Bag specification"
                    options={specificationOptions}
                    loading={growBagPoolsQuery.isLoading}
                    value={values.grow_bag_specification_id}
                    placeholder="Search specification…"
                    emptyMessage="No Grow Bag specifications available"
                    onChange={(specId) => setValue("grow_bag_specification_id", specId, { shouldValidate: true })}
                  />
                </Field>
              )}

              <dl className="text-sm">
                <div>
                  <dt className="text-ink-muted">Available capacity</dt>
                  <dd className="font-medium text-ink">{availablePlantCapacity.toLocaleString()} plants</dd>
                </div>
              </dl>
            </>
          )}
        </fieldset>
      )}

      <fieldset className="grid grid-cols-1 gap-4 rounded-xl border border-border-subtle bg-surface p-4 sm:grid-cols-2">
        <legend className="px-1 text-sm font-semibold text-ink">Transfer date/time</legend>
        <Field label="Date" error={errors.effective_date?.message}>
          <input type="date" {...register("effective_date")} className={inputClass} />
        </Field>
        <Field label="Time" error={errors.effective_time_of_day?.message}>
          <input type="time" {...register("effective_time_of_day")} className={inputClass} />
        </Field>
      </fieldset>

      <fieldset className="flex flex-col gap-4 rounded-xl border border-border-subtle bg-surface p-4">
        <legend className="px-1 text-sm font-semibold text-ink">Note (optional)</legend>
        <textarea {...register("note")} className={`${inputClass} min-h-20`} rows={2} />
      </fieldset>

      {serverError && (
        <p role="alert" className={errorClass}>
          {friendlyMutationErrorMessage(serverError)}
        </p>
      )}

      <div>
        <button
          type="submit"
          disabled={
            !values.source_intervines_table_id || !values.destination_grow_gutter_id ||
            !values.grow_bag_specification_id || !values.plant_count
          }
          className="min-h-11 rounded-md bg-brand-700 px-4 text-sm font-medium text-white hover:bg-brand-800 disabled:opacity-60"
        >
          {values.plant_count > 0 ? `Transfer ${values.plant_count.toLocaleString()} plants` : "Transfer plants"}
        </button>
      </div>
    </form>
  );
}

/** Derived, not effect-driven-on-every-render: mirrors `IntervinesTransplantForm`'s
 * own "single Nursery auto-selects" precedent, but the destination Gutter
 * picker ALSO needs `destination_greenhouse_id` written into form state
 * itself (not just a local default), so a real effect is required here --
 * scoped narrowly to run only until it has actually written the value once. */
function SingleGreenhouseAutoSelect({
  greenhouseId, setValue,
}: {
  greenhouseId: string;
  setValue: (name: "destination_greenhouse_id", value: string) => void;
}) {
  useEffect(() => {
    setValue("destination_greenhouse_id", greenhouseId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [greenhouseId]);
  return null;
}
