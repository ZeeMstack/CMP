"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useEffect, useMemo, useRef, useState } from "react";
import { useForm, useWatch } from "react-hook-form";

import { FilterableSelect, type FilterableSelectOption } from "@/components/FilterableSelect";
import type { IntervinesTransplantCreate } from "@/lib/api/client";
import { AppError, friendlyMutationErrorMessage } from "@/lib/errors/adapter";
import {
  useAvailableGrowCubePools,
  useGreenhouseSetupOverview,
  useGreenhouseStructure,
  useSeedlingBiologicalTrays,
} from "@/lib/query/hooks";
import {
  DEFAULT_INTERVINES_TRANSPLANT_FORM_VALUES,
  buildIntervinesTransplantPayload,
  intervinesTransplantFormSchema,
  type IntervinesTransplantFormValues,
} from "@/lib/validation/intervinesTransplant";

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

/** VINES-OPS-001A: the InterVines Transplant compact operator workspace --
 * one Seedling source Tray, one InterVines Table, a plant count, and
 * (only when more than one option exists) a Grow Cube specification -- the
 * server allocates the actual Grow Cubes. One transaction workspace
 * (configure -> review -> confirm), matching the established InterSalads/
 * Leafy Production Transfer form pattern, deliberately far more compact
 * since there is no N×M allocation matrix to build here. */
export function IntervinesTransplantForm({
  farmId,
  restrictToBatchId,
  onSubmit,
  isSubmitting,
  serverError,
}: {
  farmId: string;
  restrictToBatchId?: string;
  onSubmit: (
    batchId: string,
    payload: IntervinesTransplantCreate,
    tableCode: string,
  ) => void;
  isSubmitting: boolean;
  serverError?: AppError | null;
}) {
  const [step, setStep] = useState<"configure" | "review">("configure");
  const [clientCommandId, setClientCommandId] = useState(() => crypto.randomUUID());
  const lastSubmittedFingerprintRef = useRef<string | null>(null);
  const [nurseryGreenhouseId, setNurseryGreenhouseId] = useState("");

  const initial = nowDateAndTime();
  const {
    register, control, setValue, getValues, trigger, formState: { errors },
  } = useForm<IntervinesTransplantFormValues>({
    resolver: zodResolver(intervinesTransplantFormSchema),
    defaultValues: {
      ...DEFAULT_INTERVINES_TRANSPLANT_FORM_VALUES,
      effective_date: initial.date,
      effective_time_of_day: initial.time,
    },
    mode: "onBlur",
  });
  // `useWatch` (never bare `watch()`) mirrors `IntersaladsTransplantForm`'s
  // own established, proven-reliable pattern -- `watch()`'s return value
  // cannot be safely memoized (see that form's own extended comment on the
  // real bug this avoids), and React Compiler flags it as incompatible.
  const values = useWatch({ control }) as IntervinesTransplantFormValues;
  const batchId = values.batch_id;

  const traysQuery = useSeedlingBiologicalTrays(farmId);
  const growCubePoolsQuery = useAvailableGrowCubePools(farmId);
  const overviewQuery = useGreenhouseSetupOverview(farmId);
  const nurseries = useMemo(
    () => (overviewQuery.data ?? []).filter((item) => item.classification === "nursery"),
    [overviewQuery.data],
  );
  const effectiveNurseryGreenhouseId = nurseryGreenhouseId || (nurseries.length === 1 ? nurseries[0].greenhouse_id : "");

  const [prevServerError, setPrevServerError] = useState(serverError);
  if (serverError !== prevServerError) {
    setPrevServerError(serverError);
    if (serverError?.kind === "conflict") setStep("configure");
  }

  const structureQuery = useGreenhouseStructure(farmId, effectiveNurseryGreenhouseId || "__none__");
  const intervinesTables = useMemo(
    () => (effectiveNurseryGreenhouseId ? (structureQuery.data?.nursery_intervines?.tables ?? []) : []),
    [effectiveNurseryGreenhouseId, structureQuery.data],
  );
  const tableOptions: FilterableSelectOption[] = useMemo(
    () => intervinesTables.map((t) => ({ value: t.id, label: t.code, description: `capacity: ${t.capacity ?? "unlimited"}` })),
    [intervinesTables],
  );

  const eligibleSources = (traysQuery.data ?? []).filter(
    (t) =>
      t.assignment_active &&
      t.current_source_available_count > 0 &&
      (batchId ? t.batch_id === batchId : restrictToBatchId ? t.batch_id === restrictToBatchId : true),
  );
  const establishedBatch = (traysQuery.data ?? []).find((t) => t.batch_id === batchId);

  const growCubePools = useMemo(() => growCubePoolsQuery.data ?? [], [growCubePoolsQuery.data]);
  // Only NAMED specifications are ever offered as an explicit filter choice
  // -- the backend's `grow_cube_specification_id` has exactly two states,
  // "this one specific CarrierSpecification" or "no filter at all" (every
  // Grow Cube regardless of specification); there is no third wire value
  // meaning "only the unspecified ones", so a pool of unspecified Grow
  // Cubes is never rendered as a pickable option here -- it simply stays
  // part of the "no filter" total shown before/without an explicit pick.
  const namedPools = useMemo(() => growCubePools.filter((p) => p.specification_id != null), [growCubePools]);
  const showSpecificationPicker = namedPools.length > 1;
  const specificationOptions: FilterableSelectOption[] = useMemo(
    () =>
      namedPools.map((p) => ({
        value: p.specification_id as string,
        label: p.specification?.code ?? p.specification_id ?? "",
        description: `${p.available_count.toLocaleString()} available`,
      })),
    [namedPools],
  );
  // `""` (the untouched default) always means "no filter" here -- shown as
  // the total across every pool, exactly matching what the backend will
  // actually select from when `grow_cube_specification_id` is omitted.
  const availableGrowCubes = values.grow_cube_specification_id
    ? (namedPools.find((p) => p.specification_id === values.grow_cube_specification_id)?.available_count ?? 0)
    : growCubePools.reduce((sum, p) => sum + p.available_count, 0);

  // Keeps the derived-but-not-typed `current_available`/`available_grow_cubes`
  // fields (used by the schema's own cross-field validation) in sync with
  // the authoritative queries -- never operator-editable themselves.
  useEffect(() => {
    setValue("available_grow_cubes", availableGrowCubes);
  }, [availableGrowCubes, setValue]);

  function selectSource(assignmentId: string) {
    const tray = (traysQuery.data ?? []).find((t) => t.batch_carrier_assignment_id === assignmentId);
    if (!tray) return;
    setValue("source_assignment_id", assignmentId, { shouldValidate: true });
    setValue("tray_code", tray.tray_code);
    setValue("current_available", tray.current_source_available_count, { shouldValidate: true });
    if (!batchId) {
      setValue("batch_id", tray.batch_id);
      setValue("batch_code", tray.batch_code);
      setValue("crop_common_name", tray.crop_common_name);
      setValue("variety_name", tray.variety_name);
    }
  }

  async function goToReview() {
    // `available_grow_cubes` is normally kept in sync by the effect above,
    // but that effect can still lag one render behind this handler (e.g.
    // the Grow Cube pool query resolving in the same tick as a fast
    // sequence of field changes) -- writing it synchronously here, from the
    // SAME render closure the on-screen "Available Grow Cubes" figure was
    // just derived from, guarantees validation checks exactly what the
    // operator saw before clicking, never a stale effect-synced value.
    setValue("available_grow_cubes", availableGrowCubes);
    const valid = await trigger();
    if (valid) setStep("review");
  }

  function submitReview() {
    const finalValues = getValues();
    const table = intervinesTables.find((t) => t.id === finalValues.destination_location_id);
    const payload = buildIntervinesTransplantPayload(finalValues, clientCommandId);
    // eslint-disable-next-line @typescript-eslint/no-unused-vars -- rest-destructure to omit the key, not to use it
    const { client_command_id: _omit, ...fingerprint } = payload;
    const fingerprintJson = JSON.stringify(fingerprint);
    let idToUse = clientCommandId;
    if (lastSubmittedFingerprintRef.current !== null && lastSubmittedFingerprintRef.current !== fingerprintJson) {
      idToUse = crypto.randomUUID();
      setClientCommandId(idToUse);
    }
    lastSubmittedFingerprintRef.current = fingerprintJson;
    onSubmit(finalValues.batch_id, { ...payload, client_command_id: idToUse }, table?.code ?? finalValues.table_code);
  }

  if (step === "review") {
    const reviewValues = getValues();
    const table = intervinesTables.find((t) => t.id === reviewValues.destination_location_id);
    return (
      <div className="flex flex-col gap-4">
        <div className="flex flex-col gap-4 rounded-xl border border-border-subtle bg-surface p-4">
          <h2 className="font-serif text-base font-semibold text-ink">Review before transplanting</h2>
          <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm sm:grid-cols-3">
            <div>
              <dt className="text-ink-muted">Batch</dt>
              <dd className="font-medium text-ink">{reviewValues.batch_code}</dd>
            </div>
            <div>
              <dt className="text-ink-muted">Source Tray</dt>
              <dd className="font-medium text-ink">{reviewValues.tray_code}</dd>
            </div>
            <div>
              <dt className="text-ink-muted">Plants</dt>
              <dd className="font-medium text-ink">{reviewValues.plant_count.toLocaleString()}</dd>
            </div>
            <div>
              <dt className="text-ink-muted">Grow Cubes</dt>
              <dd className="font-medium text-ink">{reviewValues.plant_count.toLocaleString()}</dd>
            </div>
            <div>
              <dt className="text-ink-muted">InterVines Table</dt>
              <dd className="font-medium text-ink">{table?.code ?? reviewValues.table_code}</dd>
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
            {isSubmitting ? "Transferring…" : `Confirm transfer`}
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
      {nurseries.length > 1 && (
        <fieldset className="flex flex-col gap-4 rounded-xl border border-border-subtle bg-surface p-4">
          <legend className="px-1 text-sm font-semibold text-ink">Nursery Greenhouse</legend>
          <Field label="Nursery">
            <select value={nurseryGreenhouseId} onChange={(e) => setNurseryGreenhouseId(e.target.value)} className={inputClass}>
              <option value="">Select a Nursery…</option>
              {nurseries.map((n) => (
                <option key={n.greenhouse_id} value={n.greenhouse_id}>
                  {n.code}
                </option>
              ))}
            </select>
          </Field>
        </fieldset>
      )}

      <fieldset className="flex flex-col gap-4 rounded-xl border border-border-subtle bg-surface p-4">
        <legend className="px-1 text-sm font-semibold text-ink">Source Seed Tray</legend>
        <Field label="Source Batch / Tray" error={errors.source_assignment_id?.message}>
          <FilterableSelect
            aria-label="Source Batch / Tray"
            options={eligibleSources.map((t) => ({
              value: t.batch_carrier_assignment_id,
              label: t.tray_code,
              description: `${t.batch_code} — ${t.current_source_available_count.toLocaleString()} available`,
            }))}
            value={values.source_assignment_id}
            loading={traysQuery.isLoading}
            placeholder="Search Tray by code…"
            emptyMessage={batchId ? "No other eligible Trays on this Batch" : "No eligible source Trays"}
            onChange={selectSource}
          />
        </Field>
        {values.source_assignment_id && establishedBatch && (
          <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm sm:grid-cols-3">
            <div>
              <dt className="text-ink-muted">Batch</dt>
              <dd className="font-medium text-ink">{establishedBatch.batch_code}</dd>
            </div>
            <div>
              <dt className="text-ink-muted">Crop / Variety</dt>
              <dd className="font-medium text-ink">
                {establishedBatch.crop_common_name} / {establishedBatch.variety_name}
              </dd>
            </div>
            <div>
              <dt className="text-ink-muted">Available plants</dt>
              <dd className="font-medium text-ink">{values.current_available.toLocaleString()}</dd>
            </div>
          </dl>
        )}
      </fieldset>

      {values.source_assignment_id && (
        <fieldset className="flex flex-col gap-4 rounded-xl border border-border-subtle bg-surface p-4">
          <legend className="px-1 text-sm font-semibold text-ink">Destination</legend>
          <Field label="InterVines Table" error={errors.destination_location_id?.message}>
            <FilterableSelect
              aria-label="InterVines Table"
              options={tableOptions}
              loading={Boolean(effectiveNurseryGreenhouseId) && structureQuery.isLoading}
              value={values.destination_location_id}
              placeholder="Search Table by code…"
              emptyMessage="No InterVines Tables configured in this Nursery"
              onChange={(tableId) => {
                const table = tableOptions.find((t) => t.value === tableId);
                setValue("destination_location_id", tableId, { shouldValidate: true });
                setValue("table_code", table?.label ?? "");
              }}
            />
          </Field>

          <Field label="Plants to transfer" error={errors.plant_count?.message}>
            <input
              type="number" min={1} step={1} className={`${inputClassBase} w-full sm:w-40`}
              {...register("plant_count", { valueAsNumber: true })}
            />
          </Field>

          {showSpecificationPicker && (
            <Field label="Grow Cube specification" error={errors.grow_cube_specification_id?.message}>
              <FilterableSelect
                aria-label="Grow Cube specification"
                options={specificationOptions}
                loading={growCubePoolsQuery.isLoading}
                value={values.grow_cube_specification_id}
                placeholder="Search specification…"
                emptyMessage="No Grow Cube specifications available"
                onChange={(specId) => setValue("grow_cube_specification_id", specId, { shouldValidate: true })}
              />
            </Field>
          )}

          <dl className="text-sm">
            <div>
              <dt className="text-ink-muted">Available Grow Cubes</dt>
              <dd className="font-medium text-ink">{availableGrowCubes.toLocaleString()}</dd>
            </div>
          </dl>
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
          disabled={!values.source_assignment_id || !values.destination_location_id || !values.plant_count}
          className="min-h-11 rounded-md bg-brand-700 px-4 text-sm font-medium text-white hover:bg-brand-800 disabled:opacity-60"
        >
          {values.plant_count > 0 ? `Transfer ${values.plant_count.toLocaleString()} plants` : "Transfer plants"}
        </button>
      </div>
    </form>
  );
}
