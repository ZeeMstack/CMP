"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { ChevronDown, ChevronRight } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Control, UseFormSetValue, useFieldArray, useForm, useWatch } from "react-hook-form";

import { AllocationTotalsBar, type AllocationTotalsStat } from "@/components/allocation/AllocationTotalsBar";
import { CompactLossDisclosure } from "@/components/allocation/CompactLossDisclosure";
import { FilterableSelect, type FilterableSelectOption } from "@/components/FilterableSelect";
import { Button } from "@/components/ui/Button";
import type { IntersaladsTransplantCreate } from "@/lib/api/client";
import { suggestAllocations } from "@/lib/allocation/suggestAllocation";
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

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline gap-1 whitespace-nowrap text-xs">
      <span className="text-wl-text-secondary">{label}</span>
      <span className="font-medium text-wl-text">{value}</span>
    </div>
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

/** One destination row -- PILOT-UX-002A: a compact always-visible summary
 * line (Plate / Table / Capacity / Assigned / Remaining); InterSalads has
 * only one location level (the Table itself, no Greenhouse/Zone/Span
 * hierarchy), so unlike the Leafy Production Transfer row the Table picker
 * stays inline rather than behind an expand toggle -- only the source-
 * allocation editor is tucked behind one, since a freshly-added row
 * already starts scoped to the current Destination Area's Table (see
 * `IntersaladsTransplantForm`'s own `destinationAreaTableId`) and most rows
 * never need more than that plus an allocation. */
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
  collapsed,
  onToggleCollapsed,
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
  collapsed: boolean;
  onToggleCollapsed: () => void;
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
  const remainingCapacity = destination.biological_position_count != null ? destination.biological_position_count - assigned : null;

  return (
    <li className="flex flex-col gap-3 rounded-lg border border-wl-border p-3">
      <div className="flex flex-wrap items-center gap-3">
        <button
          type="button"
          onClick={onToggleCollapsed}
          aria-label={`${collapsed ? "Expand" : "Collapse"} destination ${index + 1} detail`}
          aria-expanded={!collapsed}
          className="flex min-h-11 min-w-11 items-center justify-center rounded-md text-wl-text-secondary hover:bg-wl-surface-sunken"
        >
          {collapsed ? <ChevronRight size={16} /> : <ChevronDown size={16} />}
        </button>
        <span className="text-sm font-semibold text-wl-text">Destination {index + 1}</span>
        <div className="min-w-40 flex-1">
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
        </div>
        <div className="min-w-40">
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
        </div>
        <Stat label="Capacity" value={destination.biological_position_count != null ? destination.biological_position_count.toLocaleString() : "Unknown"} />
        <Stat label="Assigned" value={assigned.toLocaleString()} />
        <Stat label="Remaining" value={remainingCapacity != null ? remainingCapacity.toLocaleString() : "—"} />
        <button
          type="button"
          onClick={onRemove}
          className="min-h-11 rounded-md border border-wl-border px-3 text-xs font-medium text-wl-text hover:bg-wl-surface-sunken"
        >
          Remove
        </button>
      </div>

      {destErrors?.destination_carrier_id?.message && (
        <span className={errorClass}>{destErrors.destination_carrier_id.message}</span>
      )}
      {destErrors?.destination_location_id?.message && (
        <span className={errorClass}>{destErrors.destination_location_id.message}</span>
      )}
      {destErrors?.allocations?.message && <span className={errorClass}>{destErrors.allocations.message}</span>}

      {!collapsed && (
        <div className="flex flex-col gap-2">
          <span className={labelClass}>Source allocations</span>
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
                    className="min-h-11 rounded-md border border-wl-border px-2 text-xs font-medium text-wl-text hover:bg-wl-surface-sunken"
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
            className="min-h-11 self-start rounded-md border border-wl-border px-3 text-xs font-medium text-wl-text hover:bg-wl-surface-sunken disabled:opacity-50"
          >
            Add source allocation
          </button>
          {destination.destination_location_id && occupantsQuery.isSuccess && (
            <p className="text-xs text-wl-text-secondary">
              Table occupants (server): {occupantsQuery.data.active_occupancies.length}
            </p>
          )}
        </div>
      )}
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
  const [collapsedDestinationIds, setCollapsedDestinationIds] = useState<Set<string>>(new Set());
  const [destinationAreaTableId, setDestinationAreaTableId] = useState("");

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
        // PILOT-BLOCKER-008 A10: NULL/unconfigured table occupancy capacity
        // is NOT unlimited -- the authoritative backend rule (`movement_
        // service.py`: `effective_capacity = destination_row.capacity or 1`)
        // treats it as an effective capacity of 1 (exclusive). This is the
        // TABLE OCCUPANCY capacity, a distinct concept from a Nursery
        // Cultivation Plate's own (currently unmodeled-when-null)
        // BIOLOGICAL capacity -- never conflate the two.
        description: `capacity: ${t.capacity ?? "not configured (effective: 1)"}`,
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

  // PILOT-UX-002A section H: removing a source must not leave dangling
  // allocation entries pointing at it scattered across destinations --
  // pruning them here (rather than only flagging them via the schema's
  // existing "no longer part of the transaction" check) keeps the draft
  // itself truthful, not just eventually-blocked at Review.
  function removeSource(index: number) {
    const removedId = getValues(`sources.${index}.source_assignment_id`);
    sourcesArray.remove(index);
    getValues("destinations").forEach((destination, destinationIndex) => {
      if (destination.allocations.some((a) => a.source_assignment_id === removedId)) {
        setValue(
          `destinations.${destinationIndex}.allocations`,
          destination.allocations.filter((a) => a.source_assignment_id !== removedId),
          { shouldValidate: true },
        );
      }
    });
  }

  // A freshly-added row still needs an allocation, so it starts expanded --
  // `collapsedDestinationIds` is an opt-out set, so simply never adding
  // this row's id keeps it expanded until the operator collapses it.
  function addDestination() {
    const table = tableOptions.find((t) => t.value === destinationAreaTableId);
    destinationsArray.append({
      destination_carrier_id: "", plate_code: "", biological_position_count: null,
      destination_location_id: destinationAreaTableId, table_code: table?.label ?? "", note: "", allocations: [],
    });
  }

  function toggleDestinationCollapsed(fieldId: string) {
    setCollapsedDestinationIds((prev) => {
      const next = new Set(prev);
      if (next.has(fieldId)) next.delete(fieldId);
      else next.add(fieldId);
      return next;
    });
  }

  // PILOT-UX-002A section D: applies the Destination Area's Table to every
  // destination row that hasn't been allocated yet -- a row already
  // carrying an allocation is a row the operator has already committed to,
  // so it is never silently retargeted to a different Table.
  function applyAreaTableToUnconfiguredRows() {
    if (!destinationAreaTableId) return;
    const table = tableOptions.find((t) => t.value === destinationAreaTableId);
    getValues("destinations").forEach((destination, index) => {
      if (destination.allocations.length === 0) {
        setValue(`destinations.${index}.destination_location_id`, destinationAreaTableId, { shouldValidate: true });
        setValue(`destinations.${index}.table_code`, table?.label ?? "");
      }
    });
  }

  // PILOT-UX-002A section F: an editable proposal, never an automatic
  // transplant -- fills only destinations with a known Plate capacity and
  // no allocation of their own yet (an operator override, or a destination
  // the operator is still mid-editing, is never silently replaced). See
  // `lib/allocation/suggestAllocation.ts` for the exact fill algorithm.
  function handleSuggestAllocation() {
    const current = getValues();
    const sourceIds = new Set(current.sources.map((s) => s.source_assignment_id));
    const sourceInputs = current.sources.map((s) => ({
      sourceId: s.source_assignment_id,
      available: s.current_available - (s.transplant_damage_count + s.qc_rejection_count + s.sample_count + s.other_loss_count),
    }));
    const destinationInputs = current.destinations.map((d, index) => ({
      destinationId: String(index),
      capacity: d.biological_position_count,
      existingAllocations: d.allocations
        .filter((a) => sourceIds.has(a.source_assignment_id))
        .map((a) => ({ sourceId: a.source_assignment_id, quantity: a.quantity })),
    }));
    const result = suggestAllocations(sourceInputs, destinationInputs);
    result.filledDestinationIds.forEach((destinationIdString) => {
      const index = Number(destinationIdString);
      const rows = result.byDestinationId[destinationIdString].map((r) => ({
        source_assignment_id: r.sourceId,
        quantity: r.quantity,
      }));
      setValue(`destinations.${index}.allocations`, rows, { shouldValidate: true });
      const fieldId = destinationsArray.fields[index]?.id;
      if (fieldId) {
        setCollapsedDestinationIds((prev) => {
          if (!prev.has(fieldId)) return prev;
          const next = new Set(prev);
          next.delete(fieldId);
          return next;
        });
      }
    });
  }

  // PILOT-BLOCKER-008 A10: a NULL table capacity is NOT unlimited -- it must
  // use the same effective-capacity-of-1 rule the backend authoritatively
  // enforces (`movement_service.py`: `destination_row.capacity or 1`).
  // Previously this skipped the over-capacity check entirely for an
  // unconfigured table, silently letting the draft allocate more than one
  // destination row onto it with no warning, only for the backend to
  // reject it at submit.
  const tableOverCapacity = Object.entries(occupancyByTable).some(([tableId, occ]) => {
    const effectiveCapacity = occ.capacity ?? 1;
    const draftCount = values.destinations.filter((d) => d.destination_location_id === tableId).length;
    return occ.occupiedCount + draftCount > effectiveCapacity;
  });

  // PILOT-UX-002A section C: continuously-visible running totals, computed
  // from the exact same arithmetic helpers backing validation -- never a
  // second, independently-maintained copy of this math.
  const totalAvailable = values.sources.reduce((sum, s) => sum + s.current_available, 0);
  const totalAllocated = totalTransplantedCount(values);
  const totalLoss = totalLossCount(values);
  const totalRemainder = totalAvailable - totalAllocated - totalLoss;
  const knownCapacityDestinations = values.destinations.filter((d) => d.biological_position_count != null);
  const unknownCapacityCount = values.destinations.length - knownCapacityDestinations.length;
  const totalKnownCapacity = knownCapacityDestinations.reduce((sum, d) => sum + (d.biological_position_count ?? 0), 0);
  const totalUnusedCapacity = knownCapacityDestinations.reduce(
    (sum, d) => sum + ((d.biological_position_count ?? 0) - destinationAssignedCount(d)),
    0,
  );
  const totalsStats: AllocationTotalsStat[] = [
    { label: "Source available", value: totalAvailable.toLocaleString() },
    { label: "Allocated", value: totalAllocated.toLocaleString() },
    { label: "Source remainder", value: totalRemainder.toLocaleString() },
    { label: "Loss", value: totalLoss.toLocaleString() },
    {
      label: "Destination capacity",
      value: unknownCapacityCount > 0
        ? `${totalKnownCapacity.toLocaleString()} (+${unknownCapacityCount} unknown)`
        : totalKnownCapacity.toLocaleString(),
    },
    { label: "Unused capacity", value: totalUnusedCapacity.toLocaleString() },
  ];
  const totalsWarning = tableOverCapacity
    ? "One of the selected InterSalads Tables would exceed its known capacity with this draft."
    : totalRemainder < 0
      ? "One or more sources are over-allocated."
      : totalUnusedCapacity < 0
        ? "One or more destinations exceed capacity."
        : null;

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
        <div className="flex flex-col gap-4 rounded-xl border border-wl-border bg-wl-surface-raised p-4">
          <h2 className="font-serif text-base font-semibold text-wl-text">Review before transplanting</h2>
          <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm sm:grid-cols-3">
            <div>
              <dt className="text-wl-text-secondary">Batch</dt>
              <dd className="font-medium text-wl-text">{reviewValues.batch_code}</dd>
            </div>
            <div>
              <dt className="text-wl-text-secondary">Crop / Variety</dt>
              <dd className="font-medium text-wl-text">
                {reviewValues.crop_common_name} / {reviewValues.variety_name}
              </dd>
            </div>
            <div>
              <dt className="text-wl-text-secondary">Occurred at</dt>
              <dd className="font-medium text-wl-text">
                {reviewValues.effective_date} {reviewValues.effective_time_of_day}
              </dd>
            </div>
            <div>
              <dt className="text-wl-text-secondary">Total transplanted</dt>
              <dd className="font-medium text-wl-text">{totalTransplantedCount(reviewValues).toLocaleString()}</dd>
            </div>
            <div>
              <dt className="text-wl-text-secondary">Total losses</dt>
              <dd className="font-medium text-wl-text">{totalLossCount(reviewValues).toLocaleString()}</dd>
            </div>
          </dl>

          <div>
            <h3 className="text-sm font-semibold text-wl-text">Sources</h3>
            <ul className="divide-y divide-wl-border text-sm">
              {reviewValues.sources.map((s) => (
                <li key={s.source_assignment_id} className="flex flex-col gap-1 py-2">
                  <div className="flex items-center justify-between">
                    <span className="text-wl-text">{s.tray_code}</span>
                    <span className="text-wl-text-secondary">
                      Available {s.current_available} · Allocated{" "}
                      {sourceAllocatedTotal(reviewValues, s.source_assignment_id)} · Remaining{" "}
                      {sourceRemaining(reviewValues, s.source_assignment_id)}
                    </span>
                  </div>
                  {s.transplant_damage_count + s.qc_rejection_count + s.sample_count + s.other_loss_count > 0 && (
                    <span className="text-xs text-wl-text-secondary">
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
            <h3 className="text-sm font-semibold text-wl-text">Destinations</h3>
            <ul className="divide-y divide-wl-border text-sm">
              {reviewValues.destinations.map((d, i) => (
                <li key={i} className="flex flex-col gap-1 py-2">
                  <div className="flex items-center justify-between">
                    <span className="text-wl-text">
                      {d.plate_code} → {d.table_code}
                    </span>
                    <span className="text-wl-text-secondary">
                      {destinationAssignedCount(d).toLocaleString()} seedlings
                      {d.biological_position_count != null ? ` of ${d.biological_position_count.toLocaleString()} capacity` : ""}
                    </span>
                  </div>
                  <span className="text-xs text-wl-text-secondary">
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
          <Button type="button" variant="secondary" onClick={() => setStep("configure")} disabled={isSubmitting}>
            Back
          </Button>
          <Button type="button" variant="primary" onClick={submitReview} disabled={isSubmitting}>
            {isSubmitting ? "Transplanting…" : "Confirm transplant"}
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
      {nurseries.length > 1 && (
        <fieldset className="flex flex-col gap-4 rounded-xl border border-wl-border bg-wl-surface-raised p-4">
          <legend className="px-1 text-sm font-semibold text-wl-text">Nursery Greenhouse</legend>
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

      {values.sources.length > 0 && <AllocationTotalsBar stats={totalsStats} warning={totalsWarning} />}

      <fieldset className="flex flex-col gap-4 rounded-xl border border-wl-border bg-wl-surface-raised p-4">
        <legend className="px-1 text-sm font-semibold text-wl-text">Source Seedling Tray(s)</legend>
        {errors.sources?.message && <p className={errorClass}>{errors.sources.message}</p>}
        {establishedBatch && (
          <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm sm:grid-cols-3">
            <div>
              <dt className="text-wl-text-secondary">Batch</dt>
              <dd className="font-medium text-wl-text">{establishedBatch.batch_code}</dd>
            </div>
            <div>
              <dt className="text-wl-text-secondary">Crop / Variety</dt>
              <dd className="font-medium text-wl-text">
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
            {sourcesArray.fields.map((field, index) => {
              // `values.sources` (from `useWatch`) can briefly lag one
              // render behind `sourcesArray.fields` right after an
              // `append()` -- falling back to `field`'s own (initial, all
              // -zero) data for that one render avoids a crash without
              // ever showing a wrong non-zero total.
              const sourceValues = values.sources[index] ?? field;
              const lossTotal =
                sourceValues.transplant_damage_count + sourceValues.qc_rejection_count +
                sourceValues.sample_count + sourceValues.other_loss_count;
              return (
                <li key={field.id} className="flex flex-col gap-2 rounded-md border border-wl-border p-3">
                  <div className="flex flex-wrap items-center gap-x-6 gap-y-1">
                    <span className="text-sm font-medium text-wl-text">{field.tray_code}</span>
                    <Stat label="Available" value={field.current_available.toLocaleString()} />
                    <Stat label="Allocated" value={sourceAllocatedTotal(values, field.source_assignment_id).toLocaleString()} />
                    <Stat label="Remaining" value={sourceRemaining(values, field.source_assignment_id).toLocaleString()} />
                    <button
                      type="button"
                      onClick={() => removeSource(index)}
                      className="ml-auto min-h-11 rounded-md border border-wl-border px-3 text-xs font-medium text-wl-text hover:bg-wl-surface-sunken"
                    >
                      Remove
                    </button>
                  </div>
                  <CompactLossDisclosure total={lossTotal}>
                    <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
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
                  </CompactLossDisclosure>
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
        <fieldset className="flex flex-col gap-4 rounded-xl border border-wl-border bg-wl-surface-raised p-4">
          <legend className="px-1 text-sm font-semibold text-wl-text">Destination Plate(s)</legend>
          {errors.destinations?.message && <p className={errorClass}>{errors.destinations.message}</p>}

          <div className="rounded-lg border border-wl-border bg-wl-surface-sunken p-3">
            <span className="mb-2 block text-xs font-semibold uppercase tracking-wide text-wl-text-secondary">
              Destination area
            </span>
            <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
              <div className="min-w-40 flex-1">
                <Field label="InterSalads Table">
                  <FilterableSelect
                    aria-label="Destination area Table"
                    options={tableOptions}
                    loading={Boolean(effectiveNurseryGreenhouseId) && structureQuery.isLoading}
                    value={destinationAreaTableId}
                    placeholder="Search Table by code…"
                    emptyMessage="No InterSalads Tables configured in this Nursery"
                    onChange={setDestinationAreaTableId}
                  />
                </Field>
              </div>
              <Button
                type="button"
                variant="secondary"
                onClick={applyAreaTableToUnconfiguredRows}
                disabled={!destinationAreaTableId}
              >
                Apply to unconfigured rows
              </Button>
            </div>
            <p className="mt-2 text-xs text-wl-text-secondary">Applies to newly added destination rows below -- not to existing allocated ones.</p>
          </div>

          <div className="flex flex-wrap gap-3">
            <Button type="button" variant="secondary" onClick={addDestination}>
              Add destination Plate
            </Button>
            <Button
              type="button"
              variant="secondary"
              onClick={handleSuggestAllocation}
              disabled={destinationsArray.fields.length === 0}
            >
              Suggest allocation
            </Button>
          </div>

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
                collapsed={collapsedDestinationIds.has(field.id)}
                onToggleCollapsed={() => toggleDestinationCollapsed(field.id)}
              />
            ))}
          </ul>
        </fieldset>
      )}

      <fieldset className="grid grid-cols-1 gap-4 rounded-xl border border-wl-border bg-wl-surface-raised p-4 sm:grid-cols-2">
        <legend className="px-1 text-sm font-semibold text-wl-text">Transplant date/time</legend>
        <Field label="Date" error={errors.effective_date?.message}>
          <input type="date" {...register("effective_date")} className={inputClass} />
        </Field>
        <Field label="Time" error={errors.effective_time_of_day?.message}>
          <input type="time" {...register("effective_time_of_day")} className={inputClass} />
        </Field>
      </fieldset>

      <fieldset className="flex flex-col gap-4 rounded-xl border border-wl-border bg-wl-surface-raised p-4">
        <legend className="px-1 text-sm font-semibold text-wl-text">Note (optional)</legend>
        <textarea {...register("note")} className={`${inputClass} min-h-20`} rows={2} />
      </fieldset>

      {serverError && (
        <p role="alert" className={errorClass}>
          {friendlyMutationErrorMessage(serverError)}
        </p>
      )}

      <div>
        <Button
          type="submit"
          variant="primary"
          disabled={sourcesArray.fields.length === 0 || destinationsArray.fields.length === 0}
        >
          Review
        </Button>
      </div>
    </form>
  );
}
