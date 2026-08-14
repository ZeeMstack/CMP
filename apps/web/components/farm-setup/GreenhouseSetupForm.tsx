"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { Controller, useForm } from "react-hook-form";

import type { GreenhouseSetupCreate } from "@/lib/api/client";
import {
  DEFAULT_FORM_VALUES,
  buildGreenhouseSetupPayload,
  greenhouseSetupFormSchema,
  type GreenhouseSetupFormValues,
} from "@/lib/validation/farmSetup";

const CLASSIFICATIONS: { value: GreenhouseSetupFormValues["classification"]; label: string }[] = [
  { value: "nursery", label: "Nursery" },
  { value: "leafy_greens", label: "Leafy Greens" },
  { value: "vines", label: "Vines" },
];

const inputClass =
  "min-h-11 w-full rounded-md border border-border-subtle bg-surface px-3 text-sm text-ink focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-600";
const labelClass = "block text-sm font-medium text-ink";
const errorClass = "text-xs text-red-700";

function Field({
  label, error, children,
}: { label: string; error?: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1">
      <span className={labelClass}>{label}</span>
      {children}
      {error && <span className={errorClass}>{error}</span>}
    </label>
  );
}

export function GreenhouseSetupForm({
  onSubmit, isSubmitting, serverError,
}: {
  onSubmit: (payload: GreenhouseSetupCreate) => void;
  isSubmitting: boolean;
  serverError?: string | null;
}) {
  const [step, setStep] = useState<"configure" | "review">("configure");
  const [clientCommandId] = useState(() => crypto.randomUUID());

  const {
    register, control, watch, formState: { errors }, trigger, getValues,
  } = useForm<GreenhouseSetupFormValues>({
    resolver: zodResolver(greenhouseSetupFormSchema),
    defaultValues: DEFAULT_FORM_VALUES,
    mode: "onBlur",
  });

  const classification = watch("classification");

  async function goToReview() {
    const valid = await trigger();
    if (valid) setStep("review");
  }

  function submitReview() {
    const payload = buildGreenhouseSetupPayload(getValues(), clientCommandId);
    onSubmit(payload);
  }

  if (step === "review") {
    const values = getValues();
    const payload = buildGreenhouseSetupPayload(values, clientCommandId);
    return (
      <div className="flex flex-col gap-4">
        <ReviewSummary payload={payload} />
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
            {isSubmitting ? "Creating…" : "Create greenhouse"}
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
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <Field label="Greenhouse code" error={errors.code?.message}>
          <input {...register("code")} className={inputClass} placeholder="GH-01" />
        </Field>
        <Field label="Name (optional label)" error={errors.name?.message}>
          <input {...register("name")} className={inputClass} placeholder="Greenhouse 1" />
        </Field>
      </div>

      <fieldset className="flex flex-col gap-2">
        <legend className={labelClass}>
          Classification <span className="font-normal text-ink-muted">— cannot be changed after creation</span>
        </legend>
        <div className="flex flex-wrap gap-2">
          {CLASSIFICATIONS.map((c) => (
            <label
              key={c.value}
              className={`flex min-h-11 cursor-pointer items-center gap-2 rounded-md border px-3 text-sm ${
                classification === c.value ? "border-brand-600 bg-brand-100 text-brand-800" : "border-border-subtle text-ink"
              }`}
            >
              <input type="radio" value={c.value} {...register("classification")} className="sr-only" />
              {c.label}
            </label>
          ))}
        </div>
      </fieldset>

      {classification === "leafy_greens" && <LeafyFields register={register} errors={errors} />}
      {classification === "vines" && <VinesFields register={register} control={control} errors={errors} />}
      {classification === "nursery" && <NurseryFields register={register} watch={watch} errors={errors} />}

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

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function LeafyFields({ register, errors }: { register: any; errors: any }) {
  return (
    <fieldset className="flex flex-col gap-4 rounded-lg border border-border-subtle p-4">
      <legend className="px-1 text-sm font-semibold text-ink">Leafy Greens structure</legend>
      <p className="text-xs text-ink-muted">Greenhouse → Zone → Span → Table. No Table Position.</p>
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <Field label="Zones" error={errors.leafy?.zoneCount?.message}>
          <input type="number" {...register("leafy.zoneCount", { valueAsNumber: true })} className={inputClass} />
        </Field>
        <Field label="Zone code prefix" error={errors.leafy?.zoneCodePrefix?.message}>
          <input {...register("leafy.zoneCodePrefix")} className={inputClass} />
        </Field>
        <Field label="Spans per zone" error={errors.leafy?.spansPerZone?.message}>
          <input type="number" {...register("leafy.spansPerZone", { valueAsNumber: true })} className={inputClass} />
        </Field>
        <Field label="Span code prefix" error={errors.leafy?.spanCodePrefix?.message}>
          <input {...register("leafy.spanCodePrefix")} className={inputClass} />
        </Field>
        <Field label="Tables per span" error={errors.leafy?.tablesPerSpan?.message}>
          <input type="number" {...register("leafy.tablesPerSpan", { valueAsNumber: true })} className={inputClass} />
        </Field>
        <Field label="Table code prefix" error={errors.leafy?.tableCodePrefix?.message}>
          <input {...register("leafy.tableCodePrefix")} className={inputClass} />
        </Field>
        <Field label="Table capacity (plates)" error={errors.leafy?.tableCapacity?.message}>
          <input type="number" {...register("leafy.tableCapacity", { valueAsNumber: true })} className={inputClass} />
        </Field>
      </div>
    </fieldset>
  );
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function VinesFields({ register, control, errors }: { register: any; control: any; errors: any }) {
  return (
    <fieldset className="flex flex-col gap-4 rounded-lg border border-border-subtle p-4">
      <legend className="px-1 text-sm font-semibold text-ink">Vines structure</legend>
      <p className="text-xs text-ink-muted">
        Greenhouse → Zone → Span → Grow Gutter → Grow Bag Position. No Gutter Side. Bag Position capacity is
        always exclusive (1) and not configurable here.
      </p>
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <Field label="Zones" error={errors.vines?.zoneCount?.message}>
          <input type="number" {...register("vines.zoneCount", { valueAsNumber: true })} className={inputClass} />
        </Field>
        <Field label="Zone code prefix" error={errors.vines?.zoneCodePrefix?.message}>
          <input {...register("vines.zoneCodePrefix")} className={inputClass} />
        </Field>
        <Field label="Spans per zone" error={errors.vines?.spansPerZone?.message}>
          <input type="number" {...register("vines.spansPerZone", { valueAsNumber: true })} className={inputClass} />
        </Field>
        <Field label="Span code prefix" error={errors.vines?.spanCodePrefix?.message}>
          <input {...register("vines.spanCodePrefix")} className={inputClass} />
        </Field>
        <Field label="Gutters per span" error={errors.vines?.guttersPerSpan?.message}>
          <input type="number" {...register("vines.guttersPerSpan", { valueAsNumber: true })} className={inputClass} />
        </Field>
        <Field label="Gutter code prefix" error={errors.vines?.gutterCodePrefix?.message}>
          <input {...register("vines.gutterCodePrefix")} className={inputClass} />
        </Field>
        <Field label="Bag positions per gutter" error={errors.vines?.bagPositionsPerGutter?.message}>
          <input type="number" {...register("vines.bagPositionsPerGutter", { valueAsNumber: true })} className={inputClass} />
        </Field>
        <Field label="Bag position code prefix" error={errors.vines?.bagPositionCodePrefix?.message}>
          <input {...register("vines.bagPositionCodePrefix")} className={inputClass} />
        </Field>
      </div>
      <Controller
        name="vines.continueGutterNumbering"
        control={control}
        render={({ field }) => (
          <label className="flex min-h-11 items-center gap-2 text-sm text-ink">
            <input
              type="checkbox"
              checked={field.value}
              onChange={(e) => field.onChange(e.target.checked)}
              className="h-4 w-4"
            />
            Continue gutter numbering across spans (e.g. Span 1: Gutters 01–08, Span 2: Gutters 09–16)
          </label>
        )}
      />
    </fieldset>
  );
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function NurseryFields({ register, watch, errors }: { register: any; watch: any; errors: any }) {
  const includeSeedingStation = watch("nursery.includeSeedingStation");
  const includeGerminationChamber = watch("nursery.includeGerminationChamber");
  const includeSeedling = watch("nursery.includeSeedling");
  const includeIntersalads = watch("nursery.includeIntersalads");
  const includeIntervines = watch("nursery.includeIntervines");
  const includeTrolley = watch("nursery.includeTrolley");
  const includeSeedingMachine = watch("nursery.includeSeedingMachine");

  return (
    <fieldset className="flex flex-col gap-5 rounded-lg border border-border-subtle p-4">
      <legend className="px-1 text-sm font-semibold text-ink">Nursery structure</legend>
      <p className="text-xs text-ink-muted">No Zone/Span. Every Nursery section below is optional -- configure any combination.</p>

      <div className="flex flex-col gap-2">
        <label className="flex min-h-11 items-center gap-2 text-sm font-medium text-ink">
          <input type="checkbox" {...register("nursery.includeSeedingStation")} className="h-4 w-4" />
          Seeding Station
        </label>
        {includeSeedingStation && (
          <div className="ml-6 grid grid-cols-2 gap-4 sm:grid-cols-3">
            <Field label="Code" error={errors.nursery?.seedingStation?.code?.message}>
              <input {...register("nursery.seedingStation.code")} className={inputClass} placeholder="SEED-01" />
            </Field>
            <Field label="Name (optional)">
              <input {...register("nursery.seedingStation.name")} className={inputClass} placeholder="Seeding Station" />
            </Field>
          </div>
        )}
      </div>

      <div className="flex flex-col gap-2">
        <label className="flex min-h-11 items-center gap-2 text-sm font-medium text-ink">
          <input type="checkbox" {...register("nursery.includeGerminationChamber")} className="h-4 w-4" />
          Germination Chamber
        </label>
        {includeGerminationChamber && (
          <div className="ml-6 grid grid-cols-2 gap-4 sm:grid-cols-3">
            <Field label="Code" error={errors.nursery?.germinationChamber?.code?.message}>
              <input {...register("nursery.germinationChamber.code")} className={inputClass} placeholder="GERM-01" />
            </Field>
            <Field label="Name (optional)">
              <input {...register("nursery.germinationChamber.name")} className={inputClass} placeholder="Germination Chamber" />
            </Field>
          </div>
        )}
      </div>

      <NurseryGroup
        title="Seedling"
        includeName="nursery.includeSeedling"
        included={includeSeedling}
        register={register}
        countName="nursery.seedlingTableCount"
        capacityName="nursery.seedlingCapacity"
        countError={errors.nursery?.seedlingTableCount?.message}
        capacityError={errors.nursery?.seedlingCapacity?.message}
        capacityLabel="Capacity (seed trays per table)"
      />
      <NurseryGroup
        title="InterSalads"
        includeName="nursery.includeIntersalads"
        included={includeIntersalads}
        register={register}
        countName="nursery.intersaladsTableCount"
        capacityName="nursery.intersaladsCapacity"
        countError={errors.nursery?.intersaladsTableCount?.message}
        capacityError={errors.nursery?.intersaladsCapacity?.message}
        capacityLabel="Capacity (nursery cultivation plates per table)"
      />
      <NurseryGroup
        title="InterVines"
        includeName="nursery.includeIntervines"
        included={includeIntervines}
        register={register}
        countName="nursery.intervinesTableCount"
        capacityName="nursery.intervinesCapacity"
        countError={errors.nursery?.intervinesTableCount?.message}
        capacityError={errors.nursery?.intervinesCapacity?.message}
        capacityLabel="Capacity (grow cubes per table)"
      />

      <div className="flex flex-col gap-2 border-t border-border-subtle pt-4">
        <p className="text-xs text-ink-muted">
          Trolleys and Seeding Machines are farm-level equipment, not part of this Nursery&apos;s physical structure --
          registering one here does not place or assign it to this greenhouse.
        </p>
        <label className="flex min-h-11 items-center gap-2 text-sm text-ink">
          <input type="checkbox" {...register("nursery.includeTrolley")} className="h-4 w-4" />
          Register a Germination Trolley (farm-level equipment)
        </label>
        {includeTrolley && (
          <div className="ml-6 grid grid-cols-2 gap-4 sm:grid-cols-3">
            <Field label="Trolley code" error={errors.nursery?.trolley?.code?.message}>
              <input {...register("nursery.trolley.code")} className={inputClass} placeholder="GT-01" />
            </Field>
            <Field label="Levels" error={errors.nursery?.trolley?.levelCount?.message}>
              <input type="number" {...register("nursery.trolley.levelCount", { valueAsNumber: true })} className={inputClass} />
            </Field>
            <Field label="Trays per level" error={errors.nursery?.trolley?.traysPerLevel?.message}>
              <input type="number" {...register("nursery.trolley.traysPerLevel", { valueAsNumber: true })} className={inputClass} />
            </Field>
          </div>
        )}
      </div>

      <div className="flex flex-col gap-2">
        <label className="flex min-h-11 items-center gap-2 text-sm text-ink">
          <input type="checkbox" {...register("nursery.includeSeedingMachine")} className="h-4 w-4" />
          Register a Seeding Machine (farm-level equipment)
        </label>
        {includeSeedingMachine && (
          <div className="ml-6 max-w-xs">
            <Field label="Seeding machine code" error={errors.nursery?.seedingMachine?.code?.message}>
              <input {...register("nursery.seedingMachine.code")} className={inputClass} placeholder="SM-01" />
            </Field>
          </div>
        )}
      </div>
      {errors.nursery?.message && <p className={errorClass}>{errors.nursery.message}</p>}
    </fieldset>
  );
}

function NurseryGroup({
  title, includeName, included, register, countName, capacityName, countError, capacityError, capacityLabel,
}: {
  title: string; includeName: string; included: boolean;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  register: any; countName: string; capacityName: string;
  countError?: string; capacityError?: string; capacityLabel: string;
}) {
  return (
    <div className="flex flex-col gap-2">
      <label className="flex min-h-11 items-center gap-2 text-sm font-medium text-ink">
        <input type="checkbox" {...register(includeName)} className="h-4 w-4" />
        {title} tables
      </label>
      {included && (
        <div className="ml-6 grid grid-cols-2 gap-4 sm:grid-cols-3">
          <Field label="Number of tables" error={countError}>
            <input type="number" {...register(countName, { valueAsNumber: true })} className={inputClass} />
          </Field>
          <Field label={capacityLabel} error={capacityError}>
            <input type="number" {...register(capacityName, { valueAsNumber: true })} className={inputClass} />
          </Field>
        </div>
      )}
    </div>
  );
}

function ReviewSummary({ payload }: { payload: GreenhouseSetupCreate }) {
  const rows: [string, string][] = [
    ["Code", payload.code],
    ["Name", payload.name],
    ["Classification", payload.classification],
  ];

  let counts: [string, number][] = [];
  let warning: string | null = null;

  if (payload.leafy) {
    const zones = payload.leafy.zones.length;
    const spans = payload.leafy.zones.reduce((sum, z) => sum + z.spans.length, 0);
    const tables = payload.leafy.zones.reduce(
      (sum, z) => sum + z.spans.reduce((s, span) => s + (span.tables ? span.tables.end - span.tables.start + 1 : 0), 0),
      0,
    );
    counts = [["Zones", zones], ["Spans", spans], ["Tables", tables]];
    if (tables > 2000) warning = `This will create ${tables.toLocaleString()} tables -- double-check the counts above.`;
  } else if (payload.vines) {
    const zones = payload.vines.zones.length;
    const spans = payload.vines.zones.reduce((sum, z) => sum + z.spans.length, 0);
    const gutters = payload.vines.zones.reduce(
      (sum, z) => sum + z.spans.reduce((s, span) => s + (span.gutters ? span.gutters.end - span.gutters.start + 1 : 0), 0),
      0,
    );
    const bagPositions = payload.vines.zones.reduce(
      (sum, z) =>
        sum +
        z.spans.reduce((s, span) => {
          const gutterCount = span.gutters ? span.gutters.end - span.gutters.start + 1 : 0;
          return s + gutterCount * (span.gutters?.bag_positions_per_gutter ?? 0);
        }, 0),
      0,
    );
    counts = [["Zones", zones], ["Spans", spans], ["Gutters", gutters], ["Grow Bag Positions", bagPositions]];
    if (bagPositions > 2000) warning = `This will create ${bagPositions.toLocaleString()} grow bag positions -- double-check the counts above.`;
  } else if (payload.nursery) {
    const n = payload.nursery;
    if (n.seeding_station) counts.push(["Seeding station", 1]);
    if (n.germination_chamber) counts.push(["Germination chamber", 1]);
    if (n.seedling_tables) counts.push(["Seedling tables", n.seedling_tables.end - n.seedling_tables.start + 1]);
    if (n.intersalads_tables) counts.push(["InterSalads tables", n.intersalads_tables.end - n.intersalads_tables.start + 1]);
    if (n.intervines_tables) counts.push(["InterVines tables", n.intervines_tables.end - n.intervines_tables.start + 1]);
    const trolleyCount = n.trolleys?.length ?? 0;
    const seedingMachineCount = n.seeding_machines?.length ?? 0;
    if (trolleyCount > 0) counts.push(["Trolleys (farm-level equipment)", trolleyCount]);
    if (seedingMachineCount > 0) counts.push(["Seeding machines (farm-level equipment)", seedingMachineCount]);
  }

  return (
    <div className="flex flex-col gap-4 rounded-lg border border-border-subtle bg-surface p-4">
      <h2 className="text-sm font-semibold text-ink">Review before creating</h2>
      <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm sm:grid-cols-3">
        {rows.map(([label, value]) => (
          <div key={label}>
            <dt className="text-ink-muted">{label}</dt>
            <dd className="font-medium text-ink">{value}</dd>
          </div>
        ))}
        {counts.map(([label, value]) => (
          <div key={label}>
            <dt className="text-ink-muted">{label}</dt>
            <dd className="font-medium text-ink">{value.toLocaleString()}</dd>
          </div>
        ))}
      </dl>
      {warning && (
        <p className="rounded-md bg-amber-100 px-3 py-2 text-xs text-amber-900" role="alert">
          {warning}
        </p>
      )}
    </div>
  );
}
