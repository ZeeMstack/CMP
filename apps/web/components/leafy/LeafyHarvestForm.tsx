"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useEffect, useMemo, useRef, useState } from "react";
import { useFieldArray, useForm } from "react-hook-form";

import { Button } from "@/components/ui/Button";
import type { HarvestablePlateRead, RecordLeafyHarvestCreate } from "@/lib/api/client";
import { AppError, friendlyMutationErrorMessage } from "@/lib/errors/adapter";
import {
  DEFAULT_LEAFY_HARVEST_LINE_FORM_VALUES,
  recordLeafyHarvestFormSchema,
  type RecordLeafyHarvestFormValues,
} from "@/lib/validation/leafyHarvest";

const inputClass =
  "min-h-11 w-full rounded-md border border-wl-border bg-wl-surface-raised px-2.5 text-sm text-wl-text tabular-nums focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-wl-focus";
const errorClass = "text-xs text-wl-flag-fg";
const thClass = "px-2.5 py-2 text-left text-xs font-medium text-wl-text-secondary";

function locationLabel(location: HarvestablePlateRead["location"]): string | null {
  if (!location) return null;
  const parts = [location.greenhouse, location.zone, location.span, location.grow_table]
    .filter((slot): slot is NonNullable<typeof slot> => Boolean(slot))
    .map((slot) => slot.code);
  return parts.length > 0 ? parts.join(" / ") : null;
}

function nowDateAndTime() {
  const now = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  return {
    date: `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`,
    time: `${pad(now.getHours())}:${pad(now.getMinutes())}`,
  };
}

/** HARVEST-OPS-001 SLICE 2: "Record Harvest" -- one command, one CropBatch,
 * one or more Production Plate source rows, each with independent Heads
 * harvested / Raw harvested weight / note.
 *
 * PILOT-UX-003: membership (which Plates are included) is still owned by the
 * parent page (`HarvestablePlatesPanel`'s Add/Remove), but this form is no
 * longer remounted via a `key={selectedAssignmentIds.join(",")}` on every
 * add/remove -- that wiped every already-entered value on every unrelated
 * row. Instead the form stays mounted for the life of the draft and the
 * effect below reconciles `lines` to the `plates` prop by
 * `batch_carrier_assignment_id`, appending exactly one new row per
 * newly-added Plate and removing exactly the rows for Plates no longer
 * selected -- every unaffected row survives untouched (mirrors
 * `PackingForm.tsx`'s identical `input_lines` reconciliation exactly). The
 * per-Plate rows are now a compact worksheet table (Plate / Location /
 * Heads harvested / Raw weight / Note) instead of stacked cards. */
export function LeafyHarvestForm({
  plates,
  onRemovePlate,
  onSubmit,
  isSubmitting,
  serverError,
}: {
  plates: HarvestablePlateRead[];
  onRemovePlate: (assignmentId: string) => void;
  onSubmit: (payload: RecordLeafyHarvestCreate) => void;
  isSubmitting: boolean;
  serverError?: AppError | null;
}) {
  const [step, setStep] = useState<"configure" | "review">("configure");
  const [clientCommandId, setClientCommandId] = useState(() => crypto.randomUUID());
  const lastSubmittedFingerprintRef = useRef<string | null>(null);
  // State, not a ref: written from `goToReview`, which is passed inline to
  // `handleSubmit()` in the JSX below -- the React Compiler correctly
  // refuses to let a function constructed during render write a ref
  // (unsafe: refs must never be read/written as part of rendering).
  const [reviewedPlateIdsKey, setReviewedPlateIdsKey] = useState<string | null>(null);
  const initial = nowDateAndTime();

  const {
    register, control, handleSubmit, getValues, formState: { errors },
  } = useForm<RecordLeafyHarvestFormValues>({
    resolver: zodResolver(recordLeafyHarvestFormSchema),
    defaultValues: {
      batch_id: plates[0]?.batch_id ?? "",
      batch_code: plates[0]?.batch_code ?? "",
      effective_date: initial.date,
      effective_time_of_day: initial.time,
      note: "",
      lines: plates.map((p) => ({
        ...DEFAULT_LEAFY_HARVEST_LINE_FORM_VALUES,
        batch_carrier_assignment_id: p.current_batch_carrier_assignment_id,
        production_plate_code: p.production_plate_code,
        current_living_heads: p.current_living_heads,
      })),
    },
    mode: "onBlur",
  });
  const { fields, append, remove } = useFieldArray({ control, name: "lines" });
  const plateIdsKey = plates.map((p) => p.current_batch_carrier_assignment_id).join(",");
  const plateById = useMemo(
    () => new Map(plates.map((p) => [p.current_batch_carrier_assignment_id, p])),
    [plates],
  );

  // Reconcile `lines` to the current `plates` prop by id, in place -- never
  // a full reset. Removals first, then append exactly the Plates not
  // already represented. Keyed on the id set/order, not the `plates` array
  // reference (a new reference on every parent render).
  useEffect(() => {
    const propIds = plates.map((p) => p.current_batch_carrier_assignment_id);
    const current = getValues("lines");
    const removeIndices = current.reduce<number[]>((acc, line, idx) => {
      if (!propIds.includes(line.batch_carrier_assignment_id)) acc.push(idx);
      return acc;
    }, []);
    if (removeIndices.length > 0) remove(removeIndices);
    const remainingIds = current
      .filter((_, idx) => !removeIndices.includes(idx))
      .map((line) => line.batch_carrier_assignment_id);
    for (const plate of plates) {
      if (remainingIds.includes(plate.current_batch_carrier_assignment_id)) continue;
      append({
        ...DEFAULT_LEAFY_HARVEST_LINE_FORM_VALUES,
        batch_carrier_assignment_id: plate.current_batch_carrier_assignment_id,
        production_plate_code: plate.production_plate_code,
        current_living_heads: plate.current_living_heads,
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [plateIdsKey]);

  // Never show a stale Review: if the selected-Plate set changes while the
  // operator is on Review (e.g. they added/removed a Plate from the panel
  // below without leaving this tab), drop back to Configure so totals are
  // always recomputed from the current lines, never a frozen snapshot.
  // Adjusted directly during render (React's own blessed pattern for
  // resetting state in response to a changed value, mirrors the identical
  // `prevServerError` guard just below) rather than in an effect, which
  // would cause an extra, avoidable cascading render.
  const [prevPlateIdsKeyForStaleCheck, setPrevPlateIdsKeyForStaleCheck] = useState(plateIdsKey);
  if (plateIdsKey !== prevPlateIdsKeyForStaleCheck) {
    setPrevPlateIdsKeyForStaleCheck(plateIdsKey);
    if (step === "review" && reviewedPlateIdsKey !== null && reviewedPlateIdsKey !== plateIdsKey) {
      setStep("configure");
    }
  }

  // Mirrors RecordPlantLossForm.tsx's own established 409 handling exactly.
  const [prevServerError, setPrevServerError] = useState(serverError);
  if (serverError !== prevServerError) {
    setPrevServerError(serverError);
    if (serverError?.kind === "conflict") setStep("configure");
  }

  function goToReview(values: RecordLeafyHarvestFormValues) {
    void values;
    setReviewedPlateIdsKey(plateIdsKey);
    setStep("review");
  }

  function confirm() {
    const values = getValues();
    const effectiveTime = new Date(`${values.effective_date}T${values.effective_time_of_day}`).toISOString();
    const sourceLines = values.lines.map((line) => ({
      batch_carrier_assignment_id: line.batch_carrier_assignment_id,
      whole_unit_count: line.heads_harvested,
      harvested_weight_kg: String(line.raw_harvested_weight_kg),
      note: line.note.trim() || null,
    }));
    const fingerprint = JSON.stringify({
      batch_id: values.batch_id, effective_time: effectiveTime, note: values.note.trim() || null, sourceLines,
    });
    let idToUse = clientCommandId;
    if (lastSubmittedFingerprintRef.current !== null && lastSubmittedFingerprintRef.current !== fingerprint) {
      idToUse = crypto.randomUUID();
      setClientCommandId(idToUse);
    }
    lastSubmittedFingerprintRef.current = fingerprint;
    const payload: RecordLeafyHarvestCreate = {
      client_command_id: idToUse, batch_id: values.batch_id, effective_time: effectiveTime,
      produce_lot_code: `HL-${idToUse.slice(0, 8).toUpperCase()}`, note: values.note.trim() || null,
      source_lines: sourceLines,
    };
    onSubmit(payload);
  }

  if (step === "review") {
    const values = getValues();
    const totalHeads = values.lines.reduce((sum, l) => sum + (l.heads_harvested || 0), 0);
    const totalWeight = values.lines.reduce((sum, l) => sum + (l.raw_harvested_weight_kg || 0), 0);
    return (
      <div className="flex flex-col gap-4 rounded-xl border border-wl-border bg-wl-surface-raised p-4">
        <h2 className="font-serif text-base font-semibold text-wl-text">Review before recording</h2>
        <p className="text-sm text-wl-text-secondary">
          Batch <span className="font-medium text-wl-text">{values.batch_code}</span> · {values.effective_date}{" "}
          {values.effective_time_of_day}
        </p>
        <ul className="flex flex-col gap-3">
          {values.lines.map((line) => {
            const resulting = line.current_living_heads - line.heads_harvested;
            return (
              <li key={line.batch_carrier_assignment_id} className="rounded-md border border-wl-border p-3 text-sm">
                <p className="font-medium text-wl-text">{line.production_plate_code}</p>
                <dl className="mt-1 grid grid-cols-2 gap-x-4 gap-y-1">
                  <div>
                    <dt className="text-wl-text-secondary">Living before</dt>
                    <dd className="tabular-nums text-wl-text">{line.current_living_heads.toLocaleString()} heads</dd>
                  </div>
                  <div>
                    <dt className="text-wl-text-secondary">Heads harvested</dt>
                    <dd className="tabular-nums text-wl-text">{line.heads_harvested.toLocaleString()} heads</dd>
                  </div>
                  <div>
                    <dt className="text-wl-text-secondary">Expected living after</dt>
                    <dd className="tabular-nums text-wl-text">{resulting.toLocaleString()} heads</dd>
                  </div>
                  <div>
                    <dt className="text-wl-text-secondary">Raw weight</dt>
                    <dd className="tabular-nums text-wl-text">{line.raw_harvested_weight_kg} kg</dd>
                  </div>
                </dl>
                {line.note && <p className="mt-1 text-xs text-wl-text-secondary">Note: {line.note}</p>}
                {resulting === 0 && (
                  <p className="mt-1 text-xs text-wl-text-secondary">Production population will be released.</p>
                )}
              </li>
            );
          })}
        </ul>
        <dl className="grid grid-cols-2 gap-x-4 gap-y-1 rounded-md bg-wl-surface-sunken p-3 text-sm">
          <div>
            <dt className="text-wl-text-secondary">Total heads</dt>
            <dd className="tabular-nums font-medium text-wl-text">{totalHeads.toLocaleString()} heads</dd>
          </div>
          <div>
            <dt className="text-wl-text-secondary">Total raw weight</dt>
            <dd className="tabular-nums font-medium text-wl-text">{totalWeight} kg</dd>
          </div>
        </dl>
        {values.note && (
          <p className="text-sm text-wl-text-secondary">
            Note: <span className="text-wl-text">{values.note}</span>
          </p>
        )}
        {serverError && (
          <p role="alert" className={errorClass}>
            {friendlyMutationErrorMessage(serverError)}
          </p>
        )}
        <div className="flex gap-3">
          <Button type="button" variant="secondary" onClick={() => setStep("configure")} disabled={isSubmitting}>
            Back
          </Button>
          <Button type="button" variant="primary" onClick={confirm} disabled={isSubmitting}>
            {isSubmitting ? "Recording…" : "Confirm"}
          </Button>
        </div>
      </div>
    );
  }

  return (
    <form
      onSubmit={handleSubmit(goToReview)}
      className="flex flex-col gap-4 rounded-xl border border-wl-border bg-wl-surface-raised p-4"
    >
      <h2 className="font-serif text-base font-semibold text-wl-text">Record Harvest — {plates[0]?.batch_code}</h2>

      <div className="overflow-x-auto rounded-md border border-wl-border">
        <table className="w-full border-collapse text-sm">
          <thead>
            <tr className="border-b border-wl-border bg-wl-surface-sunken">
              <th className={thClass}>Plate</th>
              <th className={thClass}>Location</th>
              <th className={`${thClass} text-right`}>Living</th>
              <th className={thClass}>Heads harvested</th>
              <th className={thClass}>Raw weight (kg)</th>
              <th className={thClass}>Note</th>
              <th className={thClass} aria-hidden />
            </tr>
          </thead>
          <tbody>
            {fields.map((field, index) => {
              const plate = plateById.get(field.batch_carrier_assignment_id);
              const location = plate ? locationLabel(plate.location) : null;
              return (
                <tr key={field.id} className="border-b border-wl-border last:border-b-0 hover:bg-wl-surface-hover">
                  <td className="px-2.5 py-2 align-top text-sm font-medium text-wl-text">
                    {field.production_plate_code}
                  </td>
                  <td className="px-2.5 py-2 align-top text-xs text-wl-text-secondary">
                    {location ?? "No current location"}
                  </td>
                  <td className="px-2.5 py-2 align-top text-right text-sm tabular-nums text-wl-text-secondary">
                    {field.current_living_heads.toLocaleString()}
                  </td>
                  <td className="px-2.5 py-2 align-top">
                    <input
                      type="number" min={1} step={1} className={inputClass}
                      aria-label="Heads harvested"
                      {...register(`lines.${index}.heads_harvested`, { valueAsNumber: true })}
                    />
                    {errors.lines?.[index]?.heads_harvested && (
                      <span className={`${errorClass} block`}>{errors.lines[index]?.heads_harvested?.message}</span>
                    )}
                  </td>
                  <td className="px-2.5 py-2 align-top">
                    <input
                      type="number" min={0.001} step={0.001} className={inputClass}
                      aria-label="Raw harvested weight (kg)"
                      {...register(`lines.${index}.raw_harvested_weight_kg`, { valueAsNumber: true })}
                    />
                    {errors.lines?.[index]?.raw_harvested_weight_kg && (
                      <span className={`${errorClass} block`}>
                        {errors.lines[index]?.raw_harvested_weight_kg?.message}
                      </span>
                    )}
                  </td>
                  <td className="px-2.5 py-2 align-top">
                    <input className={inputClass} aria-label="Note" {...register(`lines.${index}.note`)} />
                  </td>
                  <td className="px-2.5 py-2 align-top">
                    <Button type="button" variant="secondary" onClick={() => onRemovePlate(field.batch_carrier_assignment_id)}>
                      Remove
                    </Button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {errors.lines?.root && <p className={errorClass}>{errors.lines.root.message}</p>}

      <dl className="grid grid-cols-2 gap-x-4 gap-y-1 rounded-md bg-wl-surface-sunken p-3 text-sm sm:grid-cols-4">
        <div>
          <dt className="text-wl-text-secondary">Plates in this Harvest</dt>
          <dd className="tabular-nums font-medium text-wl-text">{fields.length}</dd>
        </div>
      </dl>

      <label className="flex flex-col gap-1">
        <span className="text-sm font-medium text-wl-text">Note (optional)</span>
        <textarea className={`${inputClass} min-h-20`} rows={2} {...register("note")} />
        {errors.note?.message && <span className={errorClass}>{errors.note.message}</span>}
      </label>

      <fieldset className="grid grid-cols-2 gap-3">
        <label className="flex flex-col gap-1">
          <span className="text-sm font-medium text-wl-text">Date</span>
          <input type="date" className={inputClass} {...register("effective_date")} />
          {errors.effective_date?.message && <span className={errorClass}>{errors.effective_date.message}</span>}
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-sm font-medium text-wl-text">Time</span>
          <input type="time" className={inputClass} {...register("effective_time_of_day")} />
          {errors.effective_time_of_day?.message && (
            <span className={errorClass}>{errors.effective_time_of_day.message}</span>
          )}
        </label>
      </fieldset>

      {serverError && (
        <p role="alert" className={errorClass}>
          {friendlyMutationErrorMessage(serverError)}
        </p>
      )}

      <div>
        <Button type="submit" variant="primary">
          Review
        </Button>
      </div>
    </form>
  );
}
