"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useEffect, useMemo, useState } from "react";
import { useForm, useWatch } from "react-hook-form";

import { AllocationSummaryRail } from "@/components/allocation/AllocationSummaryRail";
import { FilterableSelect, type FilterableSelectOption } from "@/components/FilterableSelect";
import { SplitWorkspace } from "@/components/layout/SplitWorkspace";
import { StickyActionBar } from "@/components/layout/StickyActionBar";
import { Button } from "@/components/ui/Button";
import type { VinesProductionTransferCreate } from "@/lib/api/client";
import {
  UNCERTAIN_OUTCOME_COPY,
  settleFrozenAttempt,
  useFrozenSubmission,
  useReportCommandLocked,
} from "@/lib/commands/frozenSubmission";
import { AppError, friendlyMutationErrorMessage } from "@/lib/errors/adapter";
import { useAvailableGrowBagPools, useGreenhouseSetupOverview, useGreenhouseStructure, useIntervinesPlacements } from "@/lib/query/hooks";
import {
  DEFAULT_VINES_PRODUCTION_TRANSFER_FORM_VALUES,
  buildVinesProductionTransferPayload,
  vinesProductionTransferFormSchema,
  type VinesProductionTransferFormValues,
} from "@/lib/validation/vinesProductionTransfer";

const inputClassBase =
  "min-h-11 rounded-md border border-wl-border bg-wl-surface-raised px-3 text-sm text-wl-text focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-wl-focus";
const inputClass = `${inputClassBase} w-full`;
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
  onCommandLockedChange,
  serverError,
}: {
  farmId: string;
  onSubmit: (batchId: string, payload: VinesProductionTransferCreate, gutterCode: string) => void | Promise<unknown>;
  isSubmitting: boolean;
  /** Reports an in-flight/unresolved attempt so the page can block
   * anything that would unmount this form mid-command. */
  onCommandLockedChange?: (locked: boolean) => void;
  serverError?: AppError | null;
}) {
  const [step, setStep] = useState<"configure" | "review">("configure");
  // UX-OPS-001C/R1: one frozen attempt per actual submission (never on
  // Review/Back). The whole wire payload -- `client_command_id`,
  // `effective_time`, targets, quantities -- plus the page context it is
  // sent with is frozen on Record; an uncertain (network/5xx) outcome is
  // retried byte-identically and locks the draft; a definitive rejection
  // or success releases it so the next submission gets a new id.
  const command = useFrozenSubmission<{ batchId: string; payload: VinesProductionTransferCreate; gutterCode: string } & Record<string, unknown>>();
  useReportCommandLocked(command.outcome, onCommandLockedChange);

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

  function sendFrozen(envelope: { batchId: string; payload: VinesProductionTransferCreate; gutterCode: string }) {
    settleFrozenAttempt(command, onSubmit(envelope.batchId, envelope.payload, envelope.gutterCode));
  }

  function submitReview() {
    if (command.outcome === "uncertain") {
      const frozen = command.retry();
      if (frozen) sendFrozen(frozen);
      return;
    }
    const finalValues = getValues();
    const gutterCode = gutterOptions.find((g) => g.value === finalValues.destination_grow_gutter_id)?.label ?? finalValues.gutter_code;
    sendFrozen(
      command.submit((clientCommandId) => ({
        batchId: finalValues.batch_id,
        payload: buildVinesProductionTransferPayload(finalValues, clientCommandId),
        gutterCode,
      })),
    );
  }

  // UX-OPS-001C: rail figures -- the server allocates the actual Grow
  // Bags/Positions, so the operator-side reconciliation is source available
  // vs. plants to transfer vs. what remains on the InterVines source. The
  // two over-limit blockers mirror the schema's own refinements exactly
  // (lib/validation/vinesProductionTransfer.ts), shown live.
  const plantCount = Number.isFinite(values.plant_count) ? values.plant_count : 0;
  const railStats = values.source_intervines_table_id
    ? [
        { label: "Available plants", value: values.current_available.toLocaleString() },
        { label: "To transfer", value: plantCount.toLocaleString() },
        { label: "Source remaining", value: (values.current_available - plantCount).toLocaleString() },
        ...(values.destination_grow_gutter_id
          ? [{ label: "Available capacity", value: `${availablePlantCapacity.toLocaleString()} plants` }]
          : []),
      ]
    : [];
  const capacityBlockers = [
    values.source_intervines_table_id && plantCount > values.current_available
      ? `Cannot exceed this InterVines source's available plants (${values.current_available})`
      : null,
    values.destination_grow_gutter_id && plantCount > availablePlantCapacity
      ? `Cannot exceed the available Grow Bag capacity (${availablePlantCapacity})`
      : null,
  ].filter((b): b is string => Boolean(b));

  if (step === "review") {
    const reviewValues = getValues();
    const gutter = gutterOptions.find((g) => g.value === reviewValues.destination_grow_gutter_id);
    return (
      <div className="flex flex-col gap-4">
        <SplitWorkspace
          main={
            <div className="flex flex-col gap-4 rounded-xl border border-wl-border bg-wl-surface-raised p-4">
              <h2 className="font-serif text-base font-semibold text-wl-text">Review before transferring</h2>
              <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm sm:grid-cols-3">
                <div>
                  <dt className="text-wl-text-secondary">Batch</dt>
                  <dd className="font-medium text-wl-text">{reviewValues.batch_code}</dd>
                </div>
                <div>
                  <dt className="text-wl-text-secondary">Plants</dt>
                  <dd className="font-medium text-wl-text">{reviewValues.plant_count.toLocaleString()}</dd>
                </div>
                <div>
                  <dt className="text-wl-text-secondary">Grow Cubes retained</dt>
                  <dd className="font-medium text-wl-text">{reviewValues.plant_count.toLocaleString()}</dd>
                </div>
                <div>
                  <dt className="text-wl-text-secondary">Source</dt>
                  <dd className="font-medium text-wl-text">{reviewValues.source_table_code}</dd>
                </div>
                <div>
                  <dt className="text-wl-text-secondary">Grow Gutter</dt>
                  <dd className="font-medium text-wl-text">{gutter?.label ?? reviewValues.gutter_code}</dd>
                </div>
                <div>
                  <dt className="text-wl-text-secondary">Occurred at</dt>
                  <dd className="font-medium text-wl-text">
                    {reviewValues.effective_date} {reviewValues.effective_time_of_day}
                  </dd>
                </div>
              </dl>
              <p className="text-xs text-wl-text-secondary">
                The server allocates the specific Grow Bags and Positions; their codes appear on the receipt.
              </p>
            </div>
          }
          rail={
            <AllocationSummaryRail
              heading="Reconciliation"
              stats={railStats}
              blockers={[
                ...(serverError ? [friendlyMutationErrorMessage(serverError)] : []),
                ...(command.outcome === "uncertain" ? [UNCERTAIN_OUTCOME_COPY] : []),
              ]}
            >
              <StickyActionBar>
                <div className="flex gap-3">
                  <Button
                    type="button"
                    variant="secondary"
                    onClick={() => setStep("configure")}
                    disabled={isSubmitting || command.outcome !== "editing"}
                  >
                    Back to edit
                  </Button>
                  <Button
                    type="button"
                    variant="primary"
                    className="flex-1"
                    onClick={submitReview}
                    disabled={isSubmitting || command.outcome === "submitting"}
                  >
                    {isSubmitting || command.outcome === "submitting"
                      ? "Transferring…"
                      : command.outcome === "uncertain"
                        ? "Retry"
                        : "Record Transfer"}
                  </Button>
                </div>
              </StickyActionBar>
            </AllocationSummaryRail>
          }
        />
      </div>
    );
  }

  const canReview = Boolean(
    values.source_intervines_table_id && values.destination_grow_gutter_id &&
    values.grow_bag_specification_id && values.plant_count,
  );
  const configureHint = !values.source_intervines_table_id
    ? "Select an InterVines source to start."
    : !values.destination_grow_gutter_id
      ? "Select a destination Grow Gutter."
      : !values.plant_count
        ? "Enter the number of plants to transfer."
        : null;

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        goToReview();
      }}
      className="flex flex-col gap-4"
    >
      <SplitWorkspace
        main={
          <div className="flex flex-col gap-4">
            <fieldset className="flex flex-col gap-3 rounded-xl border border-wl-border bg-wl-surface-raised p-4">
              <legend className="px-1 text-sm font-semibold text-wl-text">Source</legend>
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
            </fieldset>

            {values.source_intervines_table_id && (
              <fieldset className="flex flex-col gap-3 rounded-xl border border-wl-border bg-wl-surface-raised p-4">
                <legend className="px-1 text-sm font-semibold text-wl-text">Destination</legend>
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

                <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
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
                    <Field label="Plants to transfer" error={errors.plant_count?.message}>
                      <input
                        type="number" min={1} step={1} className={`${inputClassBase} w-full sm:w-40`}
                        {...register("plant_count", { valueAsNumber: true })}
                      />
                    </Field>
                  )}
                </div>

                {values.destination_grow_gutter_id && showSpecificationPicker && (
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
              </fieldset>
            )}

            <fieldset className="grid grid-cols-1 gap-3 rounded-xl border border-wl-border bg-wl-surface-raised p-4 sm:grid-cols-2">
              <legend className="px-1 text-sm font-semibold text-wl-text">Transfer date/time</legend>
              <Field label="Date" error={errors.effective_date?.message}>
                <input type="date" {...register("effective_date")} className={inputClass} />
              </Field>
              <Field label="Time" error={errors.effective_time_of_day?.message}>
                <input type="time" {...register("effective_time_of_day")} className={inputClass} />
              </Field>
              <details className="sm:col-span-2">
                <summary className="cursor-pointer text-sm font-medium text-wl-text">Note (optional)</summary>
                <textarea {...register("note")} aria-label="Note" className={`${inputClass} mt-2 min-h-20`} rows={2} />
              </details>
            </fieldset>
          </div>
        }
        rail={
          <AllocationSummaryRail
            context={
              values.source_intervines_table_id && (
                <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm">
                  <div>
                    <dt className="text-xs text-wl-text-secondary">Batch</dt>
                    <dd className="font-medium text-wl-text">{values.batch_code}</dd>
                  </div>
                  <div>
                    <dt className="text-xs text-wl-text-secondary">Crop / Variety</dt>
                    <dd className="font-medium text-wl-text">
                      {values.crop_common_name}
                      {values.variety_name ? ` / ${values.variety_name}` : ""}
                    </dd>
                  </div>
                </dl>
              )
            }
            stats={railStats}
            hint={configureHint}
            blockers={[...capacityBlockers, ...(serverError ? [friendlyMutationErrorMessage(serverError)] : [])]}
          >
            <StickyActionBar>
              <Button type="submit" variant="primary" className="w-full" disabled={!canReview}>
                Review Transfer
              </Button>
            </StickyActionBar>
          </AllocationSummaryRail>
        }
      />
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
