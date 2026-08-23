"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useEffect, useMemo, useRef, useState } from "react";
import { Control, UseFormSetValue, useFieldArray, useForm, useWatch } from "react-hook-form";

import { FilterableSelect, type FilterableSelectOption } from "@/components/FilterableSelect";
import type { IntersaladsTransplantCreate } from "@/lib/api/client";
import { AppError, friendlyMutationErrorMessage } from "@/lib/errors/adapter";
import {
  useAvailableIntersaladsPlates,
  useGreenhouseSetupOverview,
  useGreenhouseStructure,
  useLocationOccupants,
  useSeedlingBiologicalTrays,
} from "@/lib/query/hooks";
import {
  DEFAULT_INTERSALADS_TRANSPLANT_FORM_VALUES,
  buildIntersaladsTransplantPayload,
  destinationAssignedCount,
  intersaladsTransplantFormSchema,
  sourceAllocatedTotal,
  sourceRemaining,
  totalLossCount,
  totalTransplantedCount,
  type IntersaladsTransplantFormValues,
} from "@/lib/validation/intersaladsTransplant";

// Deliberately split so a caller needing a non-full width (the quantity
// input below) can compose `inputClassBase` with its own width utility
// instead of appending one to `inputClass`: Tailwind's generated CSS is
// ordered by declaration, not by class-attribute source order, so
// `` `${inputClass} w-28` `` silently lost to the `w-full` already baked
// into `inputClass` -- confirmed by measuring the real rendered input at
// ~1028px wide instead of the intended ~112px, starving the sibling
// source picker down to 0px width in the same flex row.
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

/** One destination card -- section 6 (frozen): Plate, then Table, then its
 * own list of source allocations, `assigned_plant_count` always derived
 * (never a second, independently-typed number). Its own component (not
 * inlined in the parent's `.map`) because it owns a NESTED `useFieldArray`
 * (`destinations.${index}.allocations`) -- required for correct add/remove
 * reactivity, and each row's own `useLocationOccupants` call is safe here
 * (stable per mounted row, via `field.id`), reported up to the parent via
 * `onOccupancyChange` so the review step can show a draft-wide Table-
 * capacity warning without one dynamically-sized hook array in the parent. */
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
  tableOptions,
  tableOptionsLoading,
  tableCapacityById,
  sourceOptions,
  onOccupancyChange,
  errors,
}: {
  farmId: string;
  control: Control<IntersaladsTransplantFormValues>;
  setValue: UseFormSetValue<IntersaladsTransplantFormValues>;
  index: number;
  onRemove: () => void;
  allPlateOptions: FilterableSelectOption[];
  usedPlateIds: Set<string>;
  plateOptionsLoading: boolean;
  plateCapacityById: Record<string, number | null>;
  tableOptions: FilterableSelectOption[];
  tableOptionsLoading: boolean;
  tableCapacityById: Record<string, number | null>;
  sourceOptions: FilterableSelectOption[];
  onOccupancyChange: (tableId: string, occupancy: TableOccupancy) => void;
  errors: ReturnType<typeof useForm<IntersaladsTransplantFormValues>>["formState"]["errors"];
}) {
  const destination = useWatch({ control, name: `destinations.${index}` });
  const { fields, append, remove, update } = useFieldArray({
    control, name: `destinations.${index}.allocations`,
  });
  const occupantsQuery = useLocationOccupants(farmId, destination.destination_location_id || null);
  const capacityNumber = tableCapacityById[destination.destination_location_id] ?? null;
  // Excludes Plates used by OTHER destinations, but always keeps THIS
  // row's own current selection resolvable (section: real bug fix -- see
  // `allPlateOptions`'s own comment in the parent).
  const plateOptions = allPlateOptions.filter(
    (p) => p.value === destination.destination_carrier_id || !usedPlateIds.has(p.value),
  );

  // `onOccupancyChange` is a fresh closure every parent render (it isn't
  // memoized there, and shouldn't need to be just to satisfy this): calling
  // it unconditionally on every effect run would report a NEW `{...}`
  // object each time even when the reported values are unchanged, which
  // the parent's `setOccupancyByTable` treats as a genuine state change
  // (new object reference) and re-renders on -- re-rendering every
  // DestinationRow, which could re-fire this same effect again. Reporting
  // only on an actual value change breaks that cycle at the source.
  const lastReportedRef = useRef<string | null>(null);
  useEffect(() => {
    if (!destination.destination_location_id || !occupantsQuery.isSuccess) return;
    const occupiedCount = occupantsQuery.data.active_occupancies.length;
    const reportKey = `${destination.destination_location_id}:${capacityNumber}:${occupiedCount}`;
    if (lastReportedRef.current === reportKey) return;
    lastReportedRef.current = reportKey;
    onOccupancyChange(destination.destination_location_id, { capacity: capacityNumber, occupiedCount });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [destination.destination_location_id, occupantsQuery.isSuccess, occupantsQuery.data]);

  const assigned = destinationAssignedCount(destination);
  const destErrors = errors.destinations?.[index];
  const allocatedSourceIds = new Set(destination.allocations.map((a) => a.source_assignment_id));
  const selectableSources = sourceOptions.filter((s) => !allocatedSourceIds.has(s.value));

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

      <Field label="Nursery Cultivation Plate" error={destErrors?.destination_carrier_id?.message}>
        <FilterableSelect
          aria-label={`Plate for destination ${index + 1}`}
          options={plateOptions}
          loading={plateOptionsLoading}
          value={destination.destination_carrier_id}
          placeholder="Search Plate by code…"
          emptyMessage="No eligible Plates in this Farm"
          onChange={(plateId) => {
            const plate = plateOptions.find((p) => p.value === plateId);
            setValue(`destinations.${index}.destination_carrier_id`, plateId, { shouldValidate: true });
            setValue(`destinations.${index}.plate_code`, plate?.label ?? "");
            setValue(`destinations.${index}.biological_position_count`, plateCapacityById[plateId] ?? null);
          }}
        />
      </Field>

      <Field label="InterSalads Table" error={destErrors?.destination_location_id?.message}>
        <FilterableSelect
          aria-label={`Table for destination ${index + 1}`}
          options={tableOptions}
          loading={tableOptionsLoading}
          value={destination.destination_location_id}
          placeholder="Search Table by code…"
          emptyMessage="No InterSalads Tables configured in this Nursery"
          onChange={(tableId) => {
            const table = tableOptions.find((t) => t.value === tableId);
            setValue(`destinations.${index}.destination_location_id`, tableId, { shouldValidate: true });
            setValue(`destinations.${index}.table_code`, table?.label ?? "");
          }}
        />
      </Field>

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
                    placeholder="Select source Tray…"
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

export function IntersaladsTransplantForm({
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
    payload: IntersaladsTransplantCreate,
    tableCodeById: Record<string, string>,
  ) => void;
  isSubmitting: boolean;
  serverError?: AppError | null;
}) {
  const [step, setStep] = useState<"configure" | "review">("configure");
  // Section 11 (frozen): the id is reused across an exact retry (double-
  // click, network retry, or Back-without-edit) and rotated ONLY when the
  // next submit's payload materially differs from the last one actually
  // submitted -- never merely because Back was clicked. `lastSubmittedFingerprintRef`
  // holds the JSON of the last submitted wire payload with `client_command_id`
  // itself excluded (comparing the id against itself would be meaningless);
  // `null` means nothing has been submitted yet in this draft.
  const [clientCommandId, setClientCommandId] = useState(() => crypto.randomUUID());
  const lastSubmittedFingerprintRef = useRef<string | null>(null);
  const [nurseryGreenhouseId, setNurseryGreenhouseId] = useState("");
  const [occupancyByTable, setOccupancyByTable] = useState<Record<string, TableOccupancy>>({});

  const initial = nowDateAndTime();
  const {
    control, register, setValue, getValues, trigger, formState: { errors },
  } = useForm<IntersaladsTransplantFormValues>({
    resolver: zodResolver(intersaladsTransplantFormSchema),
    defaultValues: {
      ...DEFAULT_INTERSALADS_TRANSPLANT_FORM_VALUES,
      effective_date: initial.date,
      effective_time_of_day: initial.time,
    },
    mode: "onBlur",
  });
  const sourcesArray = useFieldArray({ control, name: "sources" });
  const destinationsArray = useFieldArray({ control, name: "destinations" });

  // Each destination card's own `allocations` array is a SEPARATE, nested
  // `useFieldArray` instance (in `DestinationRow`). Reading `sources`/
  // `destinations` through this component's OWN blanket `values = watch()`
  // (or even `useWatch({ control })` with no `name`) was observed, in a
  // real browser (never reproduced in the synchronous jsdom/RTL test
  // harness), to sometimes lag one render behind a nested nested
  // `useFieldArray.update()` -- a real, reproduced bug (per-source
  // "Allocated" total silently reading 0 immediately after an allocation
  // was added, even though the SAME nested update was already correctly
  // reflected inside `DestinationRow`'s own narrowly-scoped
  // `useWatch({ control, name: \`destinations.${index}\` })`). Watching
  // `sources`/`destinations` by their own specific name here, mirroring
  // that same proven-reliable narrow-path pattern, is the fix -- a
  // blanket whole-form watch's subscription granularity is the
  // discriminating factor, not "watch vs useWatch" as such.
  const watchedSources = useWatch({ control, name: "sources" });
  const watchedDestinations = useWatch({ control, name: "destinations" });
  // `useWatch({ control })` is typed as a DeepPartial of the form shape
  // (any field could theoretically be unset before the form mounts) --
  // this form's `defaultValues` always populate the full shape up front
  // (see `DEFAULT_INTERSALADS_TRANSPLANT_FORM_VALUES` above), so the
  // runtime value is always fully-shaped; the cast reflects that real
  // invariant rather than papering over a genuine possibility of missing
  // fields.
  const values = {
    ...(useWatch({ control }) as IntersaladsTransplantFormValues),
    sources: watchedSources,
    destinations: watchedDestinations,
  };
  const batchId = values.batch_id;

  const traysQuery = useSeedlingBiologicalTrays(farmId);
  const plateOptionsQuery = useAvailableIntersaladsPlates(farmId);
  const overviewQuery = useGreenhouseSetupOverview(farmId);
  const nurseries = useMemo(
    () => (overviewQuery.data ?? []).filter((item) => item.classification === "nursery"),
    [overviewQuery.data],
  );
  // Derived, not effect-driven: when exactly one Nursery exists the picker
  // fieldset itself doesn't render (see the `nurseries.length > 1` guard
  // below), so there is no explicit-selection path to conflict with --
  // defaulting here is a pure computation, not a state sync.
  const effectiveNurseryGreenhouseId = nurseryGreenhouseId || (nurseries.length === 1 ? nurseries[0].greenhouse_id : "");

  // Section 10 (frozen): a 409 means the state this draft was built
  // against has changed elsewhere. The hook has already refreshed the
  // authoritative queries (sources/Plates/Table occupants); this forces
  // the operator back to Configure to actually see and re-review that
  // refreshed state before they can submit again -- never straight back
  // to Review with stale assumptions, and never an automatic resubmit.
  // Adjusted during render (React's documented alternative to an effect
  // for "reset state when a prop changes") rather than in a `useEffect`,
  // so this never fires as a second, separately-committed render pass.
  const [prevServerError, setPrevServerError] = useState(serverError);
  if (serverError !== prevServerError) {
    setPrevServerError(serverError);
    if (serverError?.kind === "conflict") setStep("configure");
  }
  const structureQuery = useGreenhouseStructure(farmId, effectiveNurseryGreenhouseId || "__none__");
  const intersaladsTables = useMemo(
    () => (effectiveNurseryGreenhouseId ? (structureQuery.data?.nursery_intersalads?.tables ?? []) : []),
    [effectiveNurseryGreenhouseId, structureQuery.data],
  );

  const selectedSourceIds = new Set(values.sources.map((s) => s.source_assignment_id));
  const eligibleSources = (traysQuery.data ?? []).filter(
    (t) =>
      t.assignment_active &&
      t.current_source_available_count > 0 &&
      !selectedSourceIds.has(t.batch_carrier_assignment_id) &&
      (batchId ? t.batch_id === batchId : restrictToBatchId ? t.batch_id === restrictToBatchId : true),
  );
  const sourceOptions: FilterableSelectOption[] = useMemo(
    () =>
      watchedSources.map((s) => {
        const tray = (traysQuery.data ?? []).find((t) => t.batch_carrier_assignment_id === s.source_assignment_id);
        return {
          value: s.source_assignment_id,
          label: tray?.tray_code ?? s.tray_code,
          description: `${sourceRemaining({ sources: watchedSources, destinations: watchedDestinations }, s.source_assignment_id).toLocaleString()} remaining`,
        };
      }),
    [watchedSources, watchedDestinations, traysQuery.data],
  );

  // Deliberately NOT filtered by "already used by some destination" here --
  // this list is shared across every DestinationRow, and a Plate a
  // destination already has selected must remain resolvable in that SAME
  // row's own options (otherwise the picker can no longer find it to show
  // its label -- a real, reproduced bug when this used to exclude it
  // unconditionally). Each row excludes Plates used by OTHER destinations
  // itself, where it can distinguish "used by me" from "used by someone
  // else" (see DestinationRow's own `plateOptions` computation below).
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
  const tableCapacityById: Record<string, number | null> = useMemo(
    () => Object.fromEntries(intersaladsTables.map((t) => [t.id, t.capacity ?? null])),
    [intersaladsTables],
  );
  const tableOptions: FilterableSelectOption[] = useMemo(
    () =>
      intersaladsTables.map((t) => ({
        value: t.id,
        label: t.code,
        description: `capacity: ${t.capacity ?? "unlimited"}`,
      })),
    [intersaladsTables],
  );

  const establishedBatch = (traysQuery.data ?? []).find((t) => t.batch_id === batchId);

  function addSource(assignmentId: string) {
    const tray = (traysQuery.data ?? []).find((t) => t.batch_carrier_assignment_id === assignmentId);
    if (!tray) return;
    if (!batchId) {
      setValue("batch_id", tray.batch_id);
      setValue("batch_code", tray.batch_code);
      setValue("crop_common_name", tray.crop_common_name);
      setValue("variety_name", tray.variety_name);
    }
    sourcesArray.append({
      source_assignment_id: assignmentId,
      tray_code: tray.tray_code,
      current_available: tray.current_source_available_count,
      transplant_damage_count: 0, qc_rejection_count: 0, sample_count: 0, other_loss_count: 0,
      other_loss_note: "", note: "",
    });
  }

  function addDestination() {
    destinationsArray.append({
      destination_carrier_id: "", plate_code: "", biological_position_count: null,
      destination_location_id: "", table_code: "", note: "", allocations: [],
    });
  }

  const tableOverCapacity = Object.entries(occupancyByTable).some(([tableId, occ]) => {
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
    const tableCodeById = Object.fromEntries(intersaladsTables.map((t) => [t.id, t.code]));
    const payload = buildIntersaladsTransplantPayload(finalValues, clientCommandId);
    // Section 11 (frozen): compare the command-relevant payload (everything
    // except client_command_id) against the last one actually submitted.
    // Unchanged (including an unmodified Back-then-resubmit) -> reuse the
    // same id. Materially different -> rotate to a new id BEFORE this
    // submit, so the backend never sees a payload change under a reused id.
    // eslint-disable-next-line @typescript-eslint/no-unused-vars -- rest-destructure to omit the key, not to use it
    const { client_command_id: _omit, ...fingerprint } = payload;
    const fingerprintJson = JSON.stringify(fingerprint);
    let idToUse = clientCommandId;
    if (lastSubmittedFingerprintRef.current !== null && lastSubmittedFingerprintRef.current !== fingerprintJson) {
      idToUse = crypto.randomUUID();
      setClientCommandId(idToUse);
    }
    lastSubmittedFingerprintRef.current = fingerprintJson;
    onSubmit(finalValues.batch_id, { ...payload, client_command_id: idToUse }, tableCodeById);
  }

  if (step === "review") {
    const reviewValues = getValues();
    return (
      <div className="flex flex-col gap-4">
        <div className="flex flex-col gap-4 rounded-lg border border-border-subtle bg-surface p-4">
          <h2 className="text-sm font-semibold text-ink">Review before transplanting</h2>
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
              <dt className="text-ink-muted">Total transplanted</dt>
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
                    <span className="text-ink">{s.tray_code}</span>
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
                      {d.plate_code} → {d.table_code}
                    </span>
                    <span className="text-ink-muted">{destinationAssignedCount(d).toLocaleString()} plants</span>
                  </div>
                  <span className="text-xs text-ink-muted">
                    {d.allocations.map((a) => {
                      const source = reviewValues.sources.find((s) => s.source_assignment_id === a.source_assignment_id);
                      return `${source?.tray_code ?? "?"}: ${a.quantity}`;
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
            {isSubmitting ? "Transplanting…" : "Confirm transplant"}
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
        <fieldset className="flex flex-col gap-4 rounded-lg border border-border-subtle p-4">
          <legend className="px-1 text-sm font-semibold text-ink">Nursery Greenhouse</legend>
          <Field label="Nursery">
            <select
              value={nurseryGreenhouseId}
              onChange={(e) => setNurseryGreenhouseId(e.target.value)}
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
        </fieldset>
      )}

      <fieldset className="flex flex-col gap-4 rounded-lg border border-border-subtle p-4">
        <legend className="px-1 text-sm font-semibold text-ink">Source Seedling Tray(s)</legend>
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
                {establishedBatch.crop_common_name} / {establishedBatch.variety_name}
              </dd>
            </div>
          </dl>
        )}
        <Field label="Add a source Tray">
          <FilterableSelect
            aria-label="Add a source Tray"
            options={eligibleSources.map((t) => ({
              value: t.batch_carrier_assignment_id,
              label: t.tray_code,
              description: `${t.batch_code} — ${t.current_source_available_count.toLocaleString()} available`,
            }))}
            value=""
            loading={traysQuery.isLoading}
            placeholder="Search Tray by code…"
            emptyMessage={batchId ? "No other eligible Trays on this Batch" : "No eligible source Trays"}
            onChange={addSource}
          />
        </Field>
        {sourcesArray.fields.length > 0 && (
          <ul className="flex flex-col gap-2">
            {sourcesArray.fields.map((field, index) => (
              <li key={field.id} className="flex flex-col gap-2 rounded-md border border-border-subtle p-3">
                <div className="flex items-center justify-between">
                  <span className="text-sm font-medium text-ink">{field.tray_code}</span>
                  <button
                    type="button"
                    onClick={() => sourcesArray.remove(index)}
                    className="min-h-11 rounded-md border border-border-subtle px-3 text-xs font-medium text-ink hover:bg-surface-subtle"
                  >
                    Remove
                  </button>
                </div>
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
                    Losses during transplant (optional)
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
            ))}
          </ul>
        )}
      </fieldset>

      {sourcesArray.fields.length > 0 && (
        <fieldset className="flex flex-col gap-4 rounded-lg border border-border-subtle p-4">
          <legend className="px-1 text-sm font-semibold text-ink">Destination Plate(s)</legend>
          {errors.destinations?.message && <p className={errorClass}>{errors.destinations.message}</p>}
          {tableOverCapacity && (
            <p role="alert" className={errorClass}>
              One of the selected InterSalads Tables would exceed its known capacity with this draft.
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
                tableOptions={tableOptions}
                tableOptionsLoading={Boolean(effectiveNurseryGreenhouseId) && structureQuery.isLoading}
                tableCapacityById={tableCapacityById}
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
            Add destination Plate
          </button>
        </fieldset>
      )}

      <fieldset className="grid grid-cols-1 gap-4 rounded-lg border border-border-subtle p-4 sm:grid-cols-2">
        <legend className="px-1 text-sm font-semibold text-ink">Transplant date/time</legend>
        <Field label="Date" error={errors.effective_date?.message}>
          <input type="date" {...register("effective_date")} className={inputClass} />
        </Field>
        <Field label="Time" error={errors.effective_time_of_day?.message}>
          <input type="time" {...register("effective_time_of_day")} className={inputClass} />
        </Field>
      </fieldset>

      <fieldset className="flex flex-col gap-4 rounded-lg border border-border-subtle p-4">
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
          disabled={sourcesArray.fields.length === 0 || destinationsArray.fields.length === 0}
          className="min-h-11 rounded-md bg-brand-700 px-4 text-sm font-medium text-white hover:bg-brand-800 disabled:opacity-60"
        >
          Review
        </button>
      </div>
    </form>
  );
}
