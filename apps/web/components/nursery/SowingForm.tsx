"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import Link from "next/link";
import { useMemo, useState } from "react";
import { Controller, useFieldArray, useForm } from "react-hook-form";

import { Button } from "@/components/ui/Button";
import { EmptyState } from "@/components/EmptyState";
import type { SowNewBatchCreate } from "@/lib/api/client";
import {
  useAssets,
  useAvailableSeedTrays,
  useCrops,
  useGreenhouseSetupOverview,
  useGreenhouseStructure,
  useSeedLots,
  useVarieties,
} from "@/lib/query/hooks";
import {
  DEFAULT_SOWING_FORM_VALUES,
  buildSowingPayload,
  sowingFormSchema,
  totalSeedsSown,
  totalSownSiteCount,
  type SowingFormValues,
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

function nowDateAndTime() {
  const now = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  return {
    date: `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`,
    time: `${pad(now.getHours())}:${pad(now.getMinutes())}`,
  };
}

export interface SowingPlanPrefill {
  seedingProgramLineId: string;
  cropId: string;
  varietyId?: string | null;
}

export function SowingForm({
  farmId, onSubmit, isSubmitting, serverError, planPrefill,
}: {
  farmId: string;
  onSubmit: (payload: SowNewBatchCreate) => void;
  isSubmitting: boolean;
  serverError?: string | null;
  planPrefill?: SowingPlanPrefill | null;
}) {
  const [step, setStep] = useState<"configure" | "review">("configure");
  const [clientCommandId] = useState(() => crypto.randomUUID());
  const [nurseryGreenhouseId, setNurseryGreenhouseId] = useState("");

  // PILOT-UX-001 (CTO correction): fast-path tray auto-allocation -- these
  // are plan-time helper inputs only, never submitted directly; the real
  // payload always comes from the `trays` field array below, one entry per
  // physical tray. Sites and seeds are kept as two separate, explicit
  // inputs -- sown_site_count is the physical capacity fact tray count is
  // derived from, seed_count is an independent biological quantity the
  // backend never assumes equals it (multiple seeds may share one site).
  // Neither field defaults from the other; the operator states both.
  const [fastSiteQty, setFastSiteQty] = useState("");
  const [fastSeedQty, setFastSeedQty] = useState("");
  const [fastSpecId, setFastSpecId] = useState("");
  const [manualMode, setManualMode] = useState(false);
  const [showTrayDetails, setShowTrayDetails] = useState(false);
  // PILOT-UX-001 (CTO correction): set only when "Distribute proportionally"
  // was the operator's explicit choice -- must stay visible in both the
  // compact summary and the Review step, and cleared the moment the
  // allocation is edited (Customize / Clear all), since it would otherwise
  // misrepresent hand-edited values as a proportional distribution.
  const [seedAllocationNote, setSeedAllocationNote] = useState<string | null>(null);

  const planCropsQuery = useCrops();
  const planVarietiesQuery = useVarieties(planPrefill?.cropId);
  const planCrop = planCropsQuery.data?.find((c) => c.id === planPrefill?.cropId);
  const planVariety = planVarietiesQuery.data?.find((v) => v.id === planPrefill?.varietyId);
  const planBanner = planPrefill && (
    <p className="rounded-md border border-wl-border-strong bg-wl-brand-subtle px-3 py-2 text-xs text-wl-brand">
      Fulfilling a Seeding Program plan line{planCrop ? ` for ${planCrop.common_name}` : ""}
      {planVariety ? ` — ${planVariety.name}` : ""}. Confirm the real Seed Lot, Seed Tray configuration, and
      quantity below — the plan does not override what actually gets sown.
    </p>
  );

  const initial = nowDateAndTime();
  const {
    register, control, watch, setValue, trigger, getValues, formState: { errors },
  } = useForm<SowingFormValues>({
    resolver: zodResolver(sowingFormSchema),
    defaultValues: { ...DEFAULT_SOWING_FORM_VALUES, effective_date: initial.date, effective_time_of_day: initial.time },
    mode: "onBlur",
  });
  const { fields, append, remove, replace } = useFieldArray({ control, name: "trays" });

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

  // PILOT-UX-001: group unselected trays by CarrierSpecification so an
  // operator can auto-allocate by quantity instead of picking each tray --
  // only specs with a known biological_position_count are eligible, since
  // the required-tray count is derived from that capacity, never invented.
  const specGroups: { id: string; label: string; capacity: number; available: typeof selectableTrays }[] = [];
  const specGroupIndex = new Map<string, number>();
  for (const tray of selectableTrays) {
    const spec = tray.specification;
    if (!spec || spec.biological_position_count == null) continue;
    let index = specGroupIndex.get(spec.id);
    if (index === undefined) {
      index = specGroups.length;
      specGroupIndex.set(spec.id, index);
      specGroups.push({
        id: spec.id,
        label: `${spec.name} · ${spec.biological_position_count.toLocaleString()} sites`,
        capacity: spec.biological_position_count,
        available: [],
      });
    }
    specGroups[index].available.push(tray);
  }
  const selectedFastGroup = specGroups.find((g) => g.id === fastSpecId) ?? null;
  const fastSiteQtyNumber = Number(fastSiteQty);
  const requestedSites =
    fastSiteQty !== "" && Number.isFinite(fastSiteQtyNumber) && fastSiteQtyNumber > 0 ? fastSiteQtyNumber : 0;
  const fastSeedQtyNumber = Number(fastSeedQty);
  const requestedSeeds =
    fastSeedQty !== "" && Number.isFinite(fastSeedQtyNumber) && fastSeedQtyNumber > 0 ? fastSeedQtyNumber : 0;
  // Required rule (CTO correction): tray count is derived ONLY from the
  // physical sown-site requirement against the tray specification's known
  // capacity -- seed count never participates in this calculation.
  const requiredTrayCount =
    selectedFastGroup && requestedSites > 0 ? Math.ceil(requestedSites / selectedFastGroup.capacity) : 0;
  const seedsBelowSites = requestedSites > 0 && requestedSeeds > 0 && requestedSeeds < requestedSites;
  const seedsEqualSites = requestedSites > 0 && requestedSeeds > 0 && requestedSeeds === requestedSites;
  const seedsExceedSites = requestedSites > 0 && requestedSeeds > 0 && requestedSeeds > requestedSites;
  const enoughTraysAvailable =
    selectedFastGroup !== null && requiredTrayCount > 0 && selectedFastGroup.available.length >= requiredTrayCount;
  const canAllocate = enoughTraysAvailable && requestedSeeds > 0 && !seedsBelowSites;

  /** Sites-only allocation -- the physical part, always unambiguous: full
   * capacity per tray except the last, which absorbs the exact remainder.
   * Never touches seed_count. */
  function allocateSitesOnly(): {
    carrier_id: string;
    code: string;
    biological_position_count: number | null;
    sown_site_count: number;
  }[] {
    if (!selectedFastGroup || requiredTrayCount === 0) return [];
    const traysToUse = selectedFastGroup.available.slice(0, requiredTrayCount);
    let remainingSites = requestedSites;
    return traysToUse.map((tray, index) => {
      const isLast = index === traysToUse.length - 1;
      const siteCount = isLast ? remainingSites : Math.min(selectedFastGroup.capacity, remainingSites);
      remainingSites -= siteCount;
      return {
        carrier_id: tray.id,
        code: tray.code,
        biological_position_count: tray.specification?.biological_position_count ?? null,
        sown_site_count: siteCount,
      };
    });
  }

  // PILOT-UX-001 (CTO correction): equal totals are unambiguous -- the
  // operator explicitly entered matching Sites/Seeds numbers, so each
  // tray's seed_count may equal its own sown_site_count directly. No
  // choice prompt needed.
  function autoAllocateEqual() {
    if (!canAllocate || !seedsEqualSites) return;
    const newTrays = allocateSitesOnly().map((t) => ({ ...t, seeds_sown: t.sown_site_count }));
    replace(newTrays);
    setSeedAllocationNote(null);
    setManualMode(false);
    setShowTrayDetails(false);
  }

  // PILOT-UX-001 (CTO correction): a larger seed total is ambiguous -- how
  // it splits across physical trays is not derivable from sites alone, so
  // this is only ever applied on the operator's explicit "Distribute
  // proportionally" action (never silently). Distribution uses the
  // largest-remainder method against each tray's own sown_site_count share
  // of the total, which is deterministic tray-level bookkeeping only --
  // never a claim about seeds per individual cell/site.
  function autoAllocateProportional() {
    if (!canAllocate || !seedsExceedSites) return;
    const sitesOnly = allocateSitesOnly();
    const totalSites = sitesOnly.reduce((sum, t) => sum + t.sown_site_count, 0);
    if (totalSites <= 0) return;
    const raw = sitesOnly.map((t) => (requestedSeeds * t.sown_site_count) / totalSites);
    const floors = raw.map((r) => Math.floor(r));
    let remainder = requestedSeeds - floors.reduce((sum, f) => sum + f, 0);
    const byFractionDesc = raw
      .map((r, index) => ({ index, fraction: r - Math.floor(r) }))
      .sort((a, b) => b.fraction - a.fraction || a.index - b.index);
    const seedCounts = [...floors];
    for (let k = 0; k < byFractionDesc.length && remainder > 0; k += 1) {
      seedCounts[byFractionDesc[k].index] += 1;
      remainder -= 1;
    }
    const newTrays = sitesOnly.map((t, index) => ({ ...t, seeds_sown: seedCounts[index] }));
    replace(newTrays);
    setSeedAllocationNote(
      "Seeds distributed proportionally to sown sites (tray-level allocation only, not a per-site/cell count).",
    );
    setManualMode(false);
    setShowTrayDetails(false);
  }

  // PILOT-UX-001 (CTO correction): the explicit alternative to proportional
  // distribution -- sites are allocated, seeds are left for the operator to
  // enter per tray via the existing editable table. Never guessed.
  function startCustomizeSeeds() {
    if (!enoughTraysAvailable) return;
    const newTrays = allocateSitesOnly().map((t) => ({ ...t, seeds_sown: 0 }));
    replace(newTrays);
    setSeedAllocationNote(null);
    setManualMode(true);
    setShowTrayDetails(true);
  }

  async function goToReview() {
    const valid = await trigger();
    if (valid) setStep("review");
  }

  function submitReview() {
    onSubmit(buildSowingPayload(getValues(), clientCommandId, planPrefill?.seedingProgramLineId));
  }

  if (step === "review") {
    const values = getValues();
    const seedLot = seedLotsQuery.data?.find((l) => l.id === values.seed_lot_id);
    const selectedSeedingStation = seedingStations.find((s) => s.id === values.seeding_station_id);
    const machine = seedingMachinesQuery.data?.find((m) => m.id === values.seeding_machine_id);
    const total = totalSeedsSown(values.trays);
    const totalSites = totalSownSiteCount(values.trays);
    return (
      <div className="flex flex-col gap-4">
        <StepIndicator step="review" />
        {planBanner}
        <div className="flex flex-col gap-4 rounded-xl border border-wl-border bg-wl-surface-raised p-4">
          <h2 className="font-serif text-base font-semibold text-wl-text">Review before sowing</h2>
          <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm sm:grid-cols-3">
            <div>
              <dt className="text-wl-text-secondary">Batch code</dt>
              <dd className="font-medium text-wl-text">generated on save</dd>
            </div>
            <div>
              <dt className="text-wl-text-secondary">Seeding Station</dt>
              <dd className="font-medium text-wl-text">{selectedSeedingStation?.code ?? "—"}</dd>
            </div>
            <div>
              <dt className="text-wl-text-secondary">Seed Lot</dt>
              <dd className="font-medium text-wl-text">{seedLot?.code ?? "—"}</dd>
            </div>
            {seedLot && (
              <>
                <div>
                  <dt className="text-wl-text-secondary">Crop</dt>
                  <dd className="font-medium text-wl-text">{seedLot.crop.common_name}</dd>
                </div>
                <div>
                  <dt className="text-wl-text-secondary">Variety</dt>
                  <dd className="font-medium text-wl-text">{seedLot.variety.name}</dd>
                </div>
              </>
            )}
            {machine && (
              <div>
                <dt className="text-wl-text-secondary">Seeding Machine</dt>
                <dd className="font-medium text-wl-text">{machine.code} (farm-level equipment)</dd>
              </div>
            )}
            <div>
              <dt className="text-wl-text-secondary">Occurred at</dt>
              <dd className="font-medium text-wl-text">
                {values.effective_date} {values.effective_time_of_day}
              </dd>
            </div>
            <div>
              <dt className="text-wl-text-secondary">Trays</dt>
              <dd className="font-medium text-wl-text">{values.trays.length}</dd>
            </div>
            <div>
              <dt className="text-wl-text-secondary">Total sown sites</dt>
              <dd className="font-medium text-wl-text">{totalSites.toLocaleString()}</dd>
            </div>
            <div>
              <dt className="text-wl-text-secondary">Total seeds sown</dt>
              <dd className="font-medium text-wl-text">{total.toLocaleString()}</dd>
            </div>
            {seedAllocationNote && (
              <div className="col-span-2 sm:col-span-3">
                <dt className="text-wl-text-secondary">Seed distribution</dt>
                <dd className="font-medium text-wl-text">{seedAllocationNote}</dd>
              </div>
            )}
          </dl>
          <button
            type="button"
            className="self-start text-xs font-medium text-wl-brand hover:underline"
            onClick={() => setShowTrayDetails((v) => !v)}
          >
            {showTrayDetails ? "Hide trays" : "Show trays"}
          </button>
          {showTrayDetails && (
            <ul className="divide-y divide-wl-border text-sm">
              {values.trays.map((tray) => (
                <li key={tray.carrier_id} className="flex items-center justify-between py-1.5">
                  <span className="text-wl-text">{tray.code}</span>
                  <span className="text-wl-text-secondary">
                    {tray.sown_site_count} sites · {tray.seeds_sown} seeds
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
        {serverError && <p role="alert" className={errorClass}>{serverError}</p>}
        <div className="flex gap-3">
          <Button type="button" variant="secondary" onClick={() => setStep("configure")} disabled={isSubmitting}>
            Back
          </Button>
          <Button type="button" variant="primary" onClick={submitReview} disabled={isSubmitting}>
            {isSubmitting ? "Sowing…" : "Sow"}
          </Button>
        </div>
      </div>
    );
  }

  const watchedSeedLotId = watch("seed_lot_id");
  const selectedSeedLot = seedLotsQuery.data?.find((l) => l.id === watchedSeedLotId);

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        goToReview();
      }}
      className="flex flex-col gap-6"
    >
      <StepIndicator step="configure" />
      {planBanner}

      <fieldset className="flex flex-col gap-4 rounded-xl border border-wl-border bg-wl-surface-raised p-4">
        <legend className="px-1 text-sm font-semibold text-wl-text">Nursery / Seeding Station</legend>
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

      <fieldset className="flex flex-col gap-4 rounded-xl border border-wl-border bg-wl-surface-raised p-4">
        <div className="flex items-center justify-between gap-2">
          <legend className="px-1 text-sm font-semibold text-wl-text">Seed Lot</legend>
          <Link href={`/farms/${farmId}/seed-lots/new`} className="text-xs font-medium text-wl-brand hover:underline">
            + Add Seed Lot
          </Link>
        </div>
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
        {selectedSeedLot && (
          <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm sm:grid-cols-3">
            <div>
              <dt className="text-wl-text-secondary">Crop</dt>
              <dd className="font-medium text-wl-text">{selectedSeedLot.crop.common_name}</dd>
            </div>
            <div>
              <dt className="text-wl-text-secondary">Variety</dt>
              <dd className="font-medium text-wl-text">{selectedSeedLot.variety.name}</dd>
            </div>
            {selectedSeedLot.supplier_name && (
              <div>
                <dt className="text-wl-text-secondary">Supplier</dt>
                <dd className="font-medium text-wl-text">{selectedSeedLot.supplier_name}</dd>
              </div>
            )}
          </dl>
        )}
      </fieldset>

      <fieldset className="flex flex-col gap-4 rounded-xl border border-wl-border bg-wl-surface-raised p-4">
        <legend className="px-1 text-sm font-semibold text-wl-text">Seeding Machine (optional)</legend>
        <p className="text-xs text-wl-text-secondary">Farm-level equipment — recorded as provenance only.</p>
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

      <fieldset className="grid grid-cols-1 gap-4 rounded-xl border border-wl-border bg-wl-surface-raised p-4 sm:grid-cols-2">
        <legend className="px-1 text-sm font-semibold text-wl-text">Sowing date/time</legend>
        <Field label="Date" error={errors.effective_date?.message}>
          <input type="date" {...register("effective_date")} className={inputClass} />
        </Field>
        <Field label="Time" error={errors.effective_time_of_day?.message}>
          <input type="time" {...register("effective_time_of_day")} className={inputClass} />
        </Field>
      </fieldset>

      <fieldset className="flex flex-col gap-4 rounded-xl border border-wl-border bg-wl-surface-raised p-4">
        <legend className="px-1 text-sm font-semibold text-wl-text">Seed Trays</legend>
        {!availableTraysQuery.isLoading && (availableTraysQuery.data ?? []).length === 0 ? (
          // PILOT-BLOCKER-001: distinguishes "nothing to select" from the
          // generic zod "Select at least one Seed Tray" validation message
          // -- the operator needs to know WHY the picker is empty and where
          // to go, not just that the form won't submit yet.
          <EmptyState
            title="No physical Seed Trays are available for this farm."
            description="Register physical Seed Tray carriers before sowing."
            action={
              <Link
                href={`/farms/${farmId}/carriers`}
                className="inline-flex min-h-11 items-center gap-1.5 rounded-md border border-wl-border bg-wl-surface-raised px-3 text-sm font-medium text-wl-text hover:bg-wl-surface-hover focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-wl-focus"
              >
                Set up Seed Trays
              </Link>
            }
          />
        ) : (
          <>
            {errors.trays?.message && <p className={errorClass}>{errors.trays.message}</p>}

            {fields.length === 0 && !manualMode && (
              // PILOT-UX-001 (CTO correction): fast path -- Sites to sow and
              // Seeds to sow are two distinct, explicit inputs. Tray count
              // and each tray's sown_site_count are derived only from Sites
              // to sow against the tray specification's known capacity;
              // Seeds to sow never influences tray count and is never
              // assumed equal to sites -- the operator states both.
              <div className="flex flex-col gap-3">
                <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
                  <Field label="Sites to sow">
                    <input
                      type="number"
                      min={1}
                      className={inputClass}
                      value={fastSiteQty}
                      onChange={(e) => setFastSiteQty(e.target.value)}
                      placeholder="e.g. 4000"
                    />
                  </Field>
                  <Field label="Seeds to sow" error={seedsBelowSites ? "Must be at least the number of sites" : undefined}>
                    <input
                      type="number"
                      min={1}
                      className={inputClass}
                      value={fastSeedQty}
                      onChange={(e) => setFastSeedQty(e.target.value)}
                      placeholder="e.g. 4000"
                    />
                  </Field>
                  <Field label="Tray specification">
                    <select className={inputClass} value={fastSpecId} onChange={(e) => setFastSpecId(e.target.value)}>
                      <option value="">Select a tray specification…</option>
                      {specGroups.map((group) => (
                        <option key={group.id} value={group.id}>
                          {group.label}
                        </option>
                      ))}
                    </select>
                  </Field>
                </div>
                <p className="text-xs text-wl-text-secondary">
                  A Seed Tray&apos;s capacity is a physical site count, not a seed count -- multiple seeds may share
                  one site. Required trays are computed from Sites to sow only.
                </p>
                {selectedFastGroup && requestedSites > 0 && (
                  <div className="flex flex-col gap-1 text-sm text-wl-text">
                    <p>
                      Required trays: <span className="font-medium">{requiredTrayCount.toLocaleString()}</span>
                    </p>
                    <p>
                      Available trays: <span className="font-medium">{selectedFastGroup.available.length.toLocaleString()}</span>
                    </p>
                    {selectedFastGroup.available.length < requiredTrayCount && (
                      <p className="text-xs text-danger-700">
                        Only {selectedFastGroup.available.length} of the {requiredTrayCount} needed Seed Trays are
                        registered.{" "}
                        <Link href={`/farms/${farmId}/carriers`} className="font-medium underline">
                          Register more Seed Trays
                        </Link>{" "}
                        or reduce the quantity.
                      </p>
                    )}
                  </div>
                )}
                {seedsExceedSites && (
                  <p className="text-xs text-wl-text-secondary">
                    Seeds to sow ({requestedSeeds.toLocaleString()}) is more than Sites to sow (
                    {requestedSites.toLocaleString()}) -- choose how to record seed counts per tray.
                  </p>
                )}
                <div className="flex flex-wrap items-center gap-3">
                  {seedsExceedSites ? (
                    <>
                      <Button
                        type="button"
                        variant="primary"
                        disabled={!canAllocate}
                        onClick={autoAllocateProportional}
                      >
                        Distribute proportionally
                      </Button>
                      <Button
                        type="button"
                        variant="secondary"
                        disabled={!enoughTraysAvailable}
                        onClick={startCustomizeSeeds}
                      >
                        Customize
                      </Button>
                    </>
                  ) : (
                    <Button type="button" variant="primary" disabled={!canAllocate} onClick={autoAllocateEqual}>
                      {requiredTrayCount > 0
                        ? `Auto-allocate ${requiredTrayCount.toLocaleString()} tray${requiredTrayCount === 1 ? "" : "s"}`
                        : "Auto-allocate trays"}
                    </Button>
                  )}
                  <button
                    type="button"
                    className="text-xs font-medium text-wl-brand hover:underline"
                    onClick={() => setManualMode(true)}
                  >
                    Select trays manually instead
                  </button>
                </div>
              </div>
            )}

            {fields.length > 0 && !manualMode && (
              // PILOT-UX-001: compact review -- individual tray rows stay
              // collapsed by default; traceability data already lives in
              // `fields`, it's just not rendered until asked for.
              <div className="flex flex-wrap items-center justify-between gap-3 border-t border-wl-border pt-3">
                <div>
                  <p className="text-sm font-medium text-wl-text">
                    {fields.length} Seed Tray{fields.length === 1 ? "" : "s"}
                  </p>
                  <p className="text-xs text-wl-text-secondary">
                    {totalSownSiteCount(watch("trays")).toLocaleString()} sown sites ·{" "}
                    {totalSeedsSown(watch("trays")).toLocaleString()} seeds
                  </p>
                  {seedAllocationNote && <p className="text-xs text-wl-text-secondary">{seedAllocationNote}</p>}
                </div>
                <div className="flex gap-2">
                  <Button type="button" variant="secondary" onClick={() => setShowTrayDetails((v) => !v)}>
                    {showTrayDetails ? "Hide trays" : "Show trays"}
                  </Button>
                  <Button
                    type="button"
                    variant="secondary"
                    onClick={() => {
                      setManualMode(true);
                      setShowTrayDetails(true);
                      setSeedAllocationNote(null);
                    }}
                  >
                    Customize allocation
                  </Button>
                </div>
              </div>
            )}

            {fields.length > 0 && !manualMode && showTrayDetails && (
              <ul className="divide-y divide-wl-border text-sm">
                {fields.map((field) => (
                  <li key={field.id} className="flex items-center justify-between py-1.5">
                    <span className="text-wl-text">{field.code}</span>
                    <span className="text-wl-text-secondary">
                      {field.sown_site_count.toLocaleString()} sites · {field.seeds_sown.toLocaleString()} seeds
                    </span>
                  </li>
                ))}
              </ul>
            )}

            {manualMode && (
              <>
                <Field label="Add a Seed Tray">
                  <select
                    className={inputClass}
                    value=""
                    onChange={(e) => {
                      const tray = selectableTrays.find((t) => t.id === e.target.value);
                      if (tray) {
                        append({
                          carrier_id: tray.id,
                          code: tray.code,
                          biological_position_count: tray.specification?.biological_position_count ?? null,
                          sown_site_count: 0,
                          seeds_sown: 0,
                        });
                      }
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
                  <ul className="divide-y divide-wl-border">
                    {fields.map((field, index) => (
                      <li key={field.id} className="flex flex-col gap-2 py-2 sm:flex-row sm:items-start sm:gap-3">
                        <div className="min-w-24">
                          <span className="text-sm font-medium text-wl-text">{field.code}</span>
                          <p className="text-xs text-wl-text-secondary">
                            {field.biological_position_count != null
                              ? `Capacity: ${field.biological_position_count.toLocaleString()}`
                              : "Capacity unknown"}
                          </p>
                        </div>
                        <div className="flex flex-1 gap-3">
                          <div className="flex-1">
                            <input
                              type="number"
                              {...register(`trays.${index}.sown_site_count`, { valueAsNumber: true })}
                              className={inputClass}
                              placeholder="Sown sites"
                              aria-label={`Sown sites for ${field.code}`}
                            />
                            {errors.trays?.[index]?.sown_site_count && (
                              <span className={errorClass}>{errors.trays[index]?.sown_site_count?.message}</span>
                            )}
                          </div>
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
                        </div>
                        <Button type="button" variant="secondary" onClick={() => remove(index)}>
                          Remove
                        </Button>
                      </li>
                    ))}
                  </ul>
                )}
                {fields.length > 0 && (
                  <p className="text-sm text-wl-text-secondary">
                    {fields.length} {fields.length === 1 ? "tray" : "trays"} selected · {totalSeedsSown(watch("trays"))}{" "}
                    total seeds sown
                  </p>
                )}
                <button
                  type="button"
                  className="self-start text-xs font-medium text-wl-text-secondary hover:underline"
                  onClick={() => {
                    replace([]);
                    setManualMode(false);
                    setSeedAllocationNote(null);
                  }}
                >
                  Clear all and start over
                </button>
              </>
            )}
          </>
        )}
      </fieldset>

      <fieldset className="flex flex-col gap-4 rounded-xl border border-wl-border bg-wl-surface-raised p-4">
        <legend className="px-1 text-sm font-semibold text-wl-text">Note (optional)</legend>
        <textarea {...register("note")} className={`${inputClass} min-h-20`} rows={2} />
      </fieldset>

      <div>
        <Button type="submit" variant="primary">
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
    <p className="text-xs font-semibold uppercase tracking-wide text-wl-brand">
      Step {step === "configure" ? "1" : "2"} of 2 · {step === "configure" ? "Configure" : "Review"}
    </p>
  );
}
