"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useEffect, useMemo, useRef, useState } from "react";
import { Control, UseFormSetValue, useFieldArray, useForm, useWatch } from "react-hook-form";

import { FilterableSelect, type FilterableSelectOption } from "@/components/FilterableSelect";
import { LeafyLocationSelector, type LeafyLocationValue } from "@/components/leafy/LeafyLocationSelector";
import { Button } from "@/components/ui/Button";
import type { LeafyProductionTransferCreate } from "@/lib/api/client";
import { AppError, friendlyMutationErrorMessage } from "@/lib/errors/adapter";
import {
  useAvailableLeafyProductionSources,
  useAvailableProductionPlates,
  useGreenhouseSetupOverview,
  useLocationOccupants,
} from "@/lib/query/hooks";
import {
  DEFAULT_LEAFY_PRODUCTION_TRANSFER_FORM_VALUES,
  buildLeafyProductionTransferPayload,
  destinationAssignedCount,
  leafyProductionTransferFormSchema,
  sourceAllocatedTotal,
  sourceRemaining,
  totalLossCount,
  totalTransplantedCount,
  type LeafyProductionTransferFormValues,
} from "@/lib/validation/leafyProductionTransfer";

// See IntersaladsTransplantForm.tsx's identical comment: `inputClassBase`
// (no width) vs `inputClass` (`w-full` baked in) must stay separate so a
// non-full-width control (the quantity input) can compose its own width
// utility instead of appending one to an already-`w-full` class -- the
// exact real-browser bug 004B.2 hit and fixed.
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

type TableOccupancy = { capacity: number | null; occupiedCount: number };

/** One destination card -- mirrors IntersaladsTransplantForm's own
 * `DestinationRow` exactly, substituting the InterSalads flat Table
 * `FilterableSelect` for `LeafyLocationSelector`'s cascading Greenhouse ->
 * Zone -> Span -> Table picker (the one structural difference Leafy
 * Production topology requires). Own nested `useFieldArray` for
 * allocations, own `useLocationOccupants` call, reports Table occupancy up
 * via `onOccupancyChange` for the same draft-wide capacity warning. */
function DestinationRow({
  farmId,
  control,
  setValue,
  index,
  onRemove,
  allPlateOptions,
  usedPlateIds,
  plateOptionsLoading,
  plateCapacityById,
  leafyGreenhouses,
  leafyGreenhousesLoading,
  sourceOptions,
  onOccupancyChange,
  errors,
}: {
  farmId: string;
  control: Control<LeafyProductionTransferFormValues>;
  setValue: UseFormSetValue<LeafyProductionTransferFormValues>;
  index: number;
  onRemove: () => void;
  allPlateOptions: FilterableSelectOption[];
  usedPlateIds: Set<string>;
  plateOptionsLoading: boolean;
  plateCapacityById: Record<string, number | null>;
  leafyGreenhouses: ReturnType<typeof useGreenhouseSetupOverview>["data"];
  leafyGreenhousesLoading: boolean;
  sourceOptions: FilterableSelectOption[];
  onOccupancyChange: (tableId: string, occupancy: TableOccupancy) => void;
  errors: ReturnType<typeof useForm<LeafyProductionTransferFormValues>>["formState"]["errors"];
}) {
  const destination = useWatch({ control, name: `destinations.${index}` });
  const { fields, append, remove, update } = useFieldArray({
    control, name: `destinations.${index}.allocations`,
  });
  const occupantsQuery = useLocationOccupants(farmId, destination.destination_location_id || null);
  const plateOptions = allPlateOptions.filter(
    (p) => p.value === destination.destination_carrier_id || !usedPlateIds.has(p.value),
  );

  // Repository domain convention (see `schema.gen.ts`'s comment on Table
  // capacity): NULL or 1 both mean effective capacity 1, since NULL means
  // "not configured" rather than "unlimited" -- never treat an unconfigured
  // Table as safe to over-fill.
  const capacityNumber = destination.table_capacity ?? 1;
  const lastReportedRef = useRef<string | null>(null);
  useEffect(() => {
    if (!destination.destination_location_id || !occupantsQuery.isSuccess) return;
    const occupiedCount = occupantsQuery.data.active_occupancies.length;
    const reportKey = `${destination.destination_location_id}:${capacityNumber}:${occupiedCount}`;
    if (lastReportedRef.current === reportKey) return;
    lastReportedRef.current = reportKey;
    onOccupancyChange(destination.destination_location_id, { capacity: capacityNumber, occupiedCount });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [destination.destination_location_id, capacityNumber, occupantsQuery.isSuccess, occupantsQuery.data]);

  const assigned = destinationAssignedCount(destination);
  const destErrors = errors.destinations?.[index];
  const allocatedSourceIds = new Set(destination.allocations.map((a) => a.source_assignment_id));
  const selectableSources = sourceOptions.filter((s) => !allocatedSourceIds.has(s.value));

  const locationValue: LeafyLocationValue = {
    leafy_greenhouse_id: destination.leafy_greenhouse_id,
    zone_id: destination.zone_id,
    span_id: destination.span_id,
    destination_location_id: destination.destination_location_id,
    table_label: destination.table_label,
    table_capacity: destination.table_capacity,
  };

  return (
    <li className="flex flex-col gap-3 rounded-lg border border-border-subtle p-3">
      <div className="flex items-start justify-between gap-2">
        <span className="text-sm font-semibold text-ink">Destination {index + 1}</span>
        <button
          type="button"
          onClick={onRemove}
          className="min-h-11 rounded-md border border-border-subtle px-3 text-xs font-medium text-ink hover:bg-surface-subtle"
        >
          Remove
        </button>
      </div>

      <Field label="Production Cultivation Plate" error={destErrors?.destination_carrier_id?.message}>
        <FilterableSelect
          aria-label={`Plate for destination ${index + 1}`}
          options={plateOptions}
          loading={plateOptionsLoading}
          value={destination.destination_carrier_id}
          placeholder="Search Plate by code…"
          emptyMessage="No eligible Production Plates in this Farm"
          onChange={(plateId) => {
            const plate = plateOptions.find((p) => p.value === plateId);
            setValue(`destinations.${index}.destination_carrier_id`, plateId, { shouldValidate: true });
            setValue(`destinations.${index}.plate_code`, plate?.label ?? "");
            setValue(`destinations.${index}.biological_position_count`, plateCapacityById[plateId] ?? null);
          }}
        />
      </Field>

      <LeafyLocationSelector
        farmId={farmId}
        leafyGreenhouses={leafyGreenhouses ?? []}
        leafyGreenhousesLoading={leafyGreenhousesLoading}
        value={locationValue}
        onChange={(next) => {
          setValue(`destinations.${index}.leafy_greenhouse_id`, next.leafy_greenhouse_id, { shouldValidate: true });
          setValue(`destinations.${index}.zone_id`, next.zone_id, { shouldValidate: true });
          setValue(`destinations.${index}.span_id`, next.span_id, { shouldValidate: true });
          setValue(`destinations.${index}.destination_location_id`, next.destination_location_id, {
            shouldValidate: true,
          });
          setValue(`destinations.${index}.table_label`, next.table_label);
          setValue(`destinations.${index}.table_capacity`, next.table_capacity);
        }}
        errors={destErrors}
      />

      <div className="flex flex-col gap-2">
        <span className={labelClass}>Source allocations</span>
        {destErrors?.allocations?.message && <span className={errorClass}>{destErrors.allocations.message}</span>}
        {fields.length > 0 && (
          <ul className="flex flex-col gap-2">
            {fields.map((field, allocationIndex) => (
              <li key={field.id} className="flex flex-col gap-2 sm:flex-row sm:items-center">
                <div className="min-w-0 sm:flex-1">
                  <FilterableSelect
                    aria-label={`Source for allocation ${allocationIndex + 1}`}
                    options={sourceOptions}
                    value={field.source_assignment_id}
                    placeholder="Select source Nursery Plate…"
                    onChange={(sourceId) => {
                      const current = destination.allocations[allocationIndex];
                      update(allocationIndex, { ...current, source_assignment_id: sourceId });
                    }}
                  />
                </div>
                <input
                  type="number"
                  min={1}
                  step={1}
                  className={`${inputClassBase} w-full sm:w-28 sm:shrink-0`}
                  aria-label={`Quantity for allocation ${allocationIndex + 1}`}
                  value={destination.allocations[allocationIndex]?.quantity ?? ""}
                  onChange={(e) => {
                    const current = destination.allocations[allocationIndex];
                    update(allocationIndex, { ...current, quantity: Number(e.target.value) });
                  }}
                />
                <button
                  type="button"
                  onClick={() => remove(allocationIndex)}
                  className="min-h-11 rounded-md border border-border-subtle px-2 text-xs font-medium text-ink hover:bg-surface-subtle"
                >
                  Remove
                </button>
              </li>
            ))}
          </ul>
        )}
        <button
          type="button"
          disabled={selectableSources.length === 0}
          onClick={() => append({ source_assignment_id: "", quantity: 0 })}
          className="min-h-11 self-start rounded-md border border-border-subtle px-3 text-xs font-medium text-ink hover:bg-surface-subtle disabled:opacity-50"
        >
          Add source allocation
        </button>
      </div>

      <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm sm:grid-cols-3">
        <div>
          <dt className="text-ink-muted">Assigned to Plate</dt>
          <dd className="font-medium text-ink">{assigned.toLocaleString()}</dd>
        </div>
        <div>
          <dt className="text-ink-muted">Plate capacity</dt>
          <dd className="font-medium text-ink">
            {destination.biological_position_count != null ? destination.biological_position_count.toLocaleString() : "Unknown"}
          </dd>
        </div>
        {destination.destination_location_id && occupantsQuery.isSuccess && (
          <div>
            <dt className="text-ink-muted">Table occupants (server)</dt>
            <dd className="font-medium text-ink">{occupantsQuery.data.active_occupancies.length}</dd>
          </div>
        )}
      </dl>
    </li>
  );
}

export function ProductionTransferForm({
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
    payload: LeafyProductionTransferCreate,
    tableLabelById: Record<string, string>,
  ) => void;
  isSubmitting: boolean;
  serverError?: AppError | null;
}) {
  const [step, setStep] = useState<"configure" | "review">("configure");
  const [clientCommandId, setClientCommandId] = useState(() => crypto.randomUUID());
  const lastSubmittedFingerprintRef = useRef<string | null>(null);
  const [occupancyByTable, setOccupancyByTable] = useState<Record<string, TableOccupancy>>({});

  const initial = nowDateAndTime();
  const {
    control, register, setValue, getValues, trigger, formState: { errors },
  } = useForm<LeafyProductionTransferFormValues>({
    resolver: zodResolver(leafyProductionTransferFormSchema),
    defaultValues: {
      ...DEFAULT_LEAFY_PRODUCTION_TRANSFER_FORM_VALUES,
      effective_date: initial.date,
      effective_time_of_day: initial.time,
    },
    mode: "onBlur",
  });
  const sourcesArray = useFieldArray({ control, name: "sources" });
  const destinationsArray = useFieldArray({ control, name: "destinations" });

  // See IntersaladsTransplantForm.tsx's identical comment: narrow, named
  // `useWatch` calls (never a blanket whole-form watch) for `sources`/
  // `destinations` specifically -- the proven fix for a real, reproduced
  // one-render-behind bug with nested `useFieldArray.update()`.
  const watchedSources = useWatch({ control, name: "sources" });
  const watchedDestinations = useWatch({ control, name: "destinations" });
  const values = {
    ...(useWatch({ control }) as LeafyProductionTransferFormValues),
    sources: watchedSources,
    destinations: watchedDestinations,
  };
  const batchId = values.batch_id;

  const sourcesQuery = useAvailableLeafyProductionSources(farmId, batchId || restrictToBatchId || undefined);
  const plateOptionsQuery = useAvailableProductionPlates(farmId);
  const overviewQuery = useGreenhouseSetupOverview(farmId);
  const leafyGreenhouses = useMemo(
    () => (overviewQuery.data ?? []).filter((item) => item.classification === "leafy_greens"),
    [overviewQuery.data],
  );

  // Section 10 (frozen, mirrors InterSalads): a 409 means the state this
  // draft was built against has changed elsewhere. Forces back to
  // Configure to see and re-review refreshed authoritative state -- never
  // straight back to Review with stale assumptions, never an automatic
  // resubmit.
  const [prevServerError, setPrevServerError] = useState(serverError);
  if (serverError !== prevServerError) {
    setPrevServerError(serverError);
    if (serverError?.kind === "conflict") setStep("configure");
  }

  const selectedSourceIds = new Set(values.sources.map((s) => s.source_assignment_id));
  const eligibleSources = (sourcesQuery.data ?? []).filter(
    (s) =>
      s.authoritative_available_count > 0 &&
      !selectedSourceIds.has(s.source_assignment_id) &&
      (batchId ? s.batch_id === batchId : restrictToBatchId ? s.batch_id === restrictToBatchId : true),
  );
  const sourceOptions: FilterableSelectOption[] = useMemo(
    () =>
      watchedSources.map((s) => {
        const source = (sourcesQuery.data ?? []).find((row) => row.source_assignment_id === s.source_assignment_id);
        return {
          value: s.source_assignment_id,
          label: source?.carrier.code ?? s.plate_code,
          description: `${sourceRemaining({ sources: watchedSources, destinations: watchedDestinations }, s.source_assignment_id).toLocaleString()} remaining`,
        };
      }),
    [watchedSources, watchedDestinations, sourcesQuery.data],
  );

  // Deliberately NOT filtered by "already used by some destination" here --
  // see IntersaladsTransplantForm.tsx's identical comment: this list is
  // shared across every DestinationRow, and a Plate a destination already
  // has selected must remain resolvable in that SAME row's own options.
  const allPlateOptions: FilterableSelectOption[] = useMemo(
    () =>
      (plateOptionsQuery.data ?? []).map((p) => ({
        value: p.id,
        label: p.code,
        description:
          p.specification?.biological_position_count != null
            ? `Capacity: ${p.specification.biological_position_count}`
            : "Capacity unknown",
      })),
    [plateOptionsQuery.data],
  );
  const usedPlateIds = new Set(values.destinations.map((d) => d.destination_carrier_id));
  const plateCapacityById: Record<string, number | null> = useMemo(
    () => Object.fromEntries((plateOptionsQuery.data ?? []).map((p) => [p.id, p.specification?.biological_position_count ?? null])),
    [plateOptionsQuery.data],
  );

  const establishedBatch = (sourcesQuery.data ?? []).find((s) => s.batch_id === batchId);

  function addSource(assignmentId: string) {
    const source = (sourcesQuery.data ?? []).find((s) => s.source_assignment_id === assignmentId);
    if (!source) return;
    if (!batchId) {
      setValue("batch_id", source.batch_id);
      setValue("batch_code", source.batch_code);
      setValue("crop_common_name", source.crop.common_name);
      setValue("variety_name", source.variety?.name ?? "");
    }
    sourcesArray.append({
      source_assignment_id: assignmentId,
      plate_code: source.carrier.code,
      current_available: source.authoritative_available_count,
      transplant_damage_count: 0, qc_rejection_count: 0, sample_count: 0, other_loss_count: 0,
      other_loss_note: "", note: "",
    });
  }

  function defaultGreenhouseIdForNewDestination(): string {
    if (leafyGreenhouses.length === 1) return leafyGreenhouses[0].greenhouse_id;
    const previous = values.destinations[values.destinations.length - 1];
    // Only the Greenhouse carries forward (operator speed, section 9 of the
    // correction ticket) -- never Zone/Span/Table, since those are far more
    // likely to legitimately differ between destinations even within the
    // same Greenhouse, and carrying them forward would risk a silent
    // wrong-Table submission the operator didn't intend.
    if (previous?.leafy_greenhouse_id) return previous.leafy_greenhouse_id;
    return "";
  }

  function addDestination() {
    destinationsArray.append({
      destination_carrier_id: "", plate_code: "", biological_position_count: null,
      leafy_greenhouse_id: defaultGreenhouseIdForNewDestination(),
      zone_id: "", span_id: "", destination_location_id: "", table_label: "", table_capacity: null,
      note: "", allocations: [],
    });
  }

  // `occupancyByTable` is append-only (never pruned when a destination's
  // Table selection is cleared or changed away from), so it can retain
  // entries for a Table no longer targeted by any current destination --
  // filtering to only currently-selected Table ids here is what keeps a
  // stale prior selection's reported occupancy from ever participating in
  // this check again (correction ticket section 4/8).
  const currentlySelectedTableIds = new Set(
    values.destinations.map((d) => d.destination_location_id).filter(Boolean),
  );
  const tableOverCapacity = Object.entries(occupancyByTable).some(([tableId, occ]) => {
    if (!currentlySelectedTableIds.has(tableId)) return false;
    if (occ.capacity == null) return false;
    const draftCount = values.destinations.filter((d) => d.destination_location_id === tableId).length;
    return occ.occupiedCount + draftCount > occ.capacity;
  });

  async function goToReview() {
    const valid = await trigger();
    if (valid && !tableOverCapacity) setStep("review");
  }

  function submitReview() {
    const finalValues = getValues();
    const tableLabelById = Object.fromEntries(
      finalValues.destinations.map((d) => [d.destination_location_id, d.table_label]),
    );
    const payload = buildLeafyProductionTransferPayload(finalValues, clientCommandId);
    // eslint-disable-next-line @typescript-eslint/no-unused-vars -- rest-destructure to omit the key, not to use it
    const { client_command_id: _omit, ...fingerprint } = payload;
    const fingerprintJson = JSON.stringify(fingerprint);
    let idToUse = clientCommandId;
    if (lastSubmittedFingerprintRef.current !== null && lastSubmittedFingerprintRef.current !== fingerprintJson) {
      idToUse = crypto.randomUUID();
      setClientCommandId(idToUse);
    }
    lastSubmittedFingerprintRef.current = fingerprintJson;
    onSubmit(finalValues.batch_id, { ...payload, client_command_id: idToUse }, tableLabelById);
  }

  if (step === "review") {
    const reviewValues = getValues();
    return (
      <div className="flex flex-col gap-4">
        <StepIndicator step="review" />
        <div className="flex flex-col gap-4 rounded-xl border border-border-subtle bg-surface p-4">
          <h2 className="font-serif text-base font-semibold text-ink">Review before transferring</h2>
          <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm sm:grid-cols-3">
            <div>
              <dt className="text-ink-muted">Batch</dt>
              <dd className="font-medium text-ink">{reviewValues.batch_code}</dd>
            </div>
            <div>
              <dt className="text-ink-muted">Crop / Variety</dt>
              <dd className="font-medium text-ink">
                {reviewValues.crop_common_name} / {reviewValues.variety_name}
              </dd>
            </div>
            <div>
              <dt className="text-ink-muted">Occurred at</dt>
              <dd className="font-medium text-ink">
                {reviewValues.effective_date} {reviewValues.effective_time_of_day}
              </dd>
            </div>
            <div>
              <dt className="text-ink-muted">Total transferred</dt>
              <dd className="font-medium text-ink">{totalTransplantedCount(reviewValues).toLocaleString()}</dd>
            </div>
            <div>
              <dt className="text-ink-muted">Total losses</dt>
              <dd className="font-medium text-ink">{totalLossCount(reviewValues).toLocaleString()}</dd>
            </div>
          </dl>

          <div>
            <h3 className="text-sm font-semibold text-ink">Sources</h3>
            <ul className="divide-y divide-border-subtle text-sm">
              {reviewValues.sources.map((s) => (
                <li key={s.source_assignment_id} className="flex flex-col gap-1 py-2">
                  <div className="flex items-center justify-between">
                    <span className="text-ink">{s.plate_code}</span>
                    <span className="text-ink-muted">
                      Available {s.current_available} · Allocated{" "}
                      {sourceAllocatedTotal(reviewValues, s.source_assignment_id)} · Remaining{" "}
                      {sourceRemaining(reviewValues, s.source_assignment_id)}
                    </span>
                  </div>
                  {s.transplant_damage_count + s.qc_rejection_count + s.sample_count + s.other_loss_count > 0 && (
                    <span className="text-xs text-ink-muted">
                      Losses: damage {s.transplant_damage_count}, rejected {s.qc_rejection_count}, sample{" "}
                      {s.sample_count}, other {s.other_loss_count}
                      {s.other_loss_note ? ` (${s.other_loss_note})` : ""}
                    </span>
                  )}
                </li>
              ))}
            </ul>
          </div>

          <div>
            <h3 className="text-sm font-semibold text-ink">Destinations</h3>
            <ul className="divide-y divide-border-subtle text-sm">
              {reviewValues.destinations.map((d, i) => (
                <li key={i} className="flex flex-col gap-1 py-2">
                  <div className="flex items-center justify-between">
                    <span className="text-ink">
                      {d.plate_code} → {d.table_label}
                    </span>
                    <span className="text-ink-muted">{destinationAssignedCount(d).toLocaleString()} plants</span>
                  </div>
                  <span className="text-xs text-ink-muted">
                    {d.allocations.map((a) => {
                      const source = reviewValues.sources.find((s) => s.source_assignment_id === a.source_assignment_id);
                      return `${source?.plate_code ?? "?"}: ${a.quantity}`;
                    }).join(", ")}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        </div>
        {serverError && (
          <p role="alert" className={errorClass}>
            {friendlyMutationErrorMessage(serverError)}
          </p>
        )}
        <div className="flex gap-3">
          <Button type="button" variant="secondary" onClick={() => setStep("configure")} disabled={isSubmitting}>
            Back
          </Button>
          <Button type="button" variant="primary" onClick={submitReview} disabled={isSubmitting}>
            {isSubmitting ? "Transferring…" : "Confirm transfer"}
          </Button>
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
      <StepIndicator step="configure" />

      <fieldset className="flex flex-col gap-4 rounded-xl border border-border-subtle bg-surface p-4">
        <legend className="px-1 text-sm font-semibold text-ink">Source Nursery Cultivation Plate(s)</legend>
        {errors.sources?.message && <p className={errorClass}>{errors.sources.message}</p>}
        {establishedBatch && (
          <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm sm:grid-cols-3">
            <div>
              <dt className="text-ink-muted">Batch</dt>
              <dd className="font-medium text-ink">{establishedBatch.batch_code}</dd>
            </div>
            <div>
              <dt className="text-ink-muted">Crop / Variety</dt>
              <dd className="font-medium text-ink">
                {establishedBatch.crop.common_name} / {establishedBatch.variety?.name ?? "—"}
              </dd>
            </div>
          </dl>
        )}
        <Field label="Add a source Nursery Plate">
          <FilterableSelect
            aria-label="Add a source Nursery Plate"
            options={eligibleSources.map((s) => ({
              value: s.source_assignment_id,
              label: s.carrier.code,
              description: `${s.batch_code} — ${s.authoritative_available_count.toLocaleString()} available${
                s.current_location ? ` — at ${s.current_location.code}` : ""
              }`,
            }))}
            value=""
            loading={sourcesQuery.isLoading}
            placeholder="Search Nursery Plate by code…"
            emptyMessage={batchId ? "No other eligible Nursery Plates on this Batch" : "No eligible source Nursery Plates"}
            onChange={addSource}
          />
        </Field>
        {sourcesArray.fields.length > 0 && (
          <ul className="flex flex-col gap-2">
            {sourcesArray.fields.map((field, index) => {
              const sourceRow = (sourcesQuery.data ?? []).find(
                (s) => s.source_assignment_id === field.source_assignment_id,
              );
              return (
                <li key={field.id} className="flex flex-col gap-2 rounded-md border border-border-subtle p-3">
                  <div className="flex items-center justify-between">
                    <span className="text-sm font-medium text-ink">{field.plate_code}</span>
                    <button
                      type="button"
                      onClick={() => sourcesArray.remove(index)}
                      className="min-h-11 rounded-md border border-border-subtle px-3 text-xs font-medium text-ink hover:bg-surface-subtle"
                    >
                      Remove
                    </button>
                  </div>
                  {sourceRow?.current_location && (
                    <p className="text-xs text-ink-muted">
                      Currently at {sourceRow.current_location.code}
                    </p>
                  )}
                  <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm sm:grid-cols-3">
                    <div>
                      <dt className="text-ink-muted">Available</dt>
                      <dd className="font-medium text-ink">{field.current_available.toLocaleString()}</dd>
                    </div>
                    <div>
                      <dt className="text-ink-muted">Allocated</dt>
                      <dd className="font-medium text-ink">
                        {sourceAllocatedTotal(values, field.source_assignment_id).toLocaleString()}
                      </dd>
                    </div>
                    <div>
                      <dt className="text-ink-muted">Remaining</dt>
                      <dd className="font-medium text-ink">
                        {sourceRemaining(values, field.source_assignment_id).toLocaleString()}
                      </dd>
                    </div>
                  </dl>
                  <details>
                    <summary className="cursor-pointer text-sm font-medium text-ink">
                      Losses during transfer (optional)
                    </summary>
                    <div className="mt-2 grid grid-cols-2 gap-3 sm:grid-cols-4">
                      <Field label="Damage">
                        <input
                          type="number" min={0} step={1} className={inputClass}
                          {...register(`sources.${index}.transplant_damage_count`, { valueAsNumber: true })}
                        />
                      </Field>
                      <Field label="QC rejected">
                        <input
                          type="number" min={0} step={1} className={inputClass}
                          {...register(`sources.${index}.qc_rejection_count`, { valueAsNumber: true })}
                        />
                      </Field>
                      <Field label="Sample">
                        <input
                          type="number" min={0} step={1} className={inputClass}
                          {...register(`sources.${index}.sample_count`, { valueAsNumber: true })}
                        />
                      </Field>
                      <Field label="Other">
                        <input
                          type="number" min={0} step={1} className={inputClass}
                          {...register(`sources.${index}.other_loss_count`, { valueAsNumber: true })}
                        />
                      </Field>
                    </div>
                    <Field
                      label={`Other loss note ${values.sources[index]?.other_loss_count > 0 ? "(required)" : "(optional)"}`}
                      error={errors.sources?.[index]?.other_loss_note?.message}
                    >
                      <input className={inputClass} {...register(`sources.${index}.other_loss_note`)} />
                    </Field>
                  </details>
                  {errors.sources?.[index]?.current_available?.message && (
                    <span className={errorClass}>{errors.sources[index]?.current_available?.message}</span>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </fieldset>

      {sourcesArray.fields.length > 0 && (
        <fieldset className="flex flex-col gap-4 rounded-xl border border-border-subtle bg-surface p-4">
          <legend className="px-1 text-sm font-semibold text-ink">Destination Production Plate(s)</legend>
          {errors.destinations?.message && <p className={errorClass}>{errors.destinations.message}</p>}
          {tableOverCapacity && (
            <p role="alert" className={errorClass}>
              One of the selected Leafy Tables would exceed its known capacity with this draft.
            </p>
          )}
          <ul className="flex flex-col gap-3">
            {destinationsArray.fields.map((field, index) => (
              <DestinationRow
                key={field.id}
                farmId={farmId}
                control={control}
                setValue={setValue}
                index={index}
                onRemove={() => destinationsArray.remove(index)}
                allPlateOptions={allPlateOptions}
                usedPlateIds={usedPlateIds}
                plateOptionsLoading={plateOptionsQuery.isLoading}
                plateCapacityById={plateCapacityById}
                leafyGreenhouses={leafyGreenhouses}
                leafyGreenhousesLoading={overviewQuery.isLoading}
                sourceOptions={sourceOptions}
                onOccupancyChange={(tableId, occ) => setOccupancyByTable((prev) => ({ ...prev, [tableId]: occ }))}
                errors={errors}
              />
            ))}
          </ul>
          <button
            type="button"
            onClick={addDestination}
            className="min-h-11 self-start rounded-md border border-border-subtle px-4 text-sm font-medium text-ink hover:bg-surface-subtle"
          >
            Add destination Production Plate
          </button>
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
        <Button type="submit" variant="primary" disabled={sourcesArray.fields.length === 0 || destinationsArray.fields.length === 0}>
          Review
        </Button>
      </div>
    </form>
  );
}

/** Purely presentational -- both steps already exist as real form/review
 * state (`step` above); this just makes the two-step configure → review
 * flow visible to the operator. */
function StepIndicator({ step }: { step: "configure" | "review" }) {
  return (
    <p className="text-xs font-semibold uppercase tracking-wide text-brand-700">
      Step {step === "configure" ? "1" : "2"} of 2 · {step === "configure" ? "Configure" : "Review"}
    </p>
  );
}
