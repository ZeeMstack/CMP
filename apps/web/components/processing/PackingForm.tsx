"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useEffect, useMemo, useRef, useState } from "react";
import { useFieldArray, useForm } from "react-hook-form";

import { PackingInputLineRow } from "@/components/processing/PackingInputLineRow";
import { ReconciliationSummary } from "@/components/processing/ReconciliationSummary";
import { Button } from "@/components/ui/Button";
import type { GradedProduceLotRead, PackingEventCreate } from "@/lib/api/client";
import { AppError, friendlyMutationErrorMessage } from "@/lib/errors/adapter";
import { selectableVersionsAt } from "@/lib/format/versionLifecycle";
import { usePackSpecificationVersions, usePackSpecifications } from "@/lib/query/hooks";
import { recordPackingFormSchema, type RecordPackingFormValues } from "@/lib/validation/packing";

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

/** POSTHARVEST-OPS-001G: "Record Packing" -- one or more input Graded
 * Produce Lots (already selected by the parent page, same convention as
 * `LeafyHarvestForm`'s `plates` prop), one Pack Specification Version, one
 * Finished Goods Lot output, reconciliation against process loss/rejection.
 * Mirrors `GradingForm.tsx`'s configure -> review -> confirm shape and
 * idempotency-key discipline exactly.
 *
 * PILOT-UX-002C: no longer remounted when the selected input set changes
 * (the parent used to pass `key={selectedIds.join(",")}`, which wiped the
 * Pack Specification/Version, Finished Goods Lot code, package count and
 * every already-edited consumed quantity on every add/remove). Instead this
 * form stays mounted for the life of the draft and the effect below
 * reconciles `input_lines` to the `lots` prop by id -- appending exactly one
 * new row per newly-added Lot and removing exactly the rows for Lots no
 * longer selected -- so every unaffected row and every top-level field
 * survives untouched. */
export function PackingForm({
  farmId,
  lots,
  onRemoveLot,
  onSubmit,
  isSubmitting,
  serverError,
}: {
  farmId: string;
  lots: GradedProduceLotRead[];
  onRemoveLot: (lotId: string) => void;
  onSubmit: (payload: PackingEventCreate) => void;
  isSubmitting: boolean;
  serverError?: AppError | null;
}) {
  const [step, setStep] = useState<"configure" | "review">("configure");
  const [clientCommandId, setClientCommandId] = useState(() => crypto.randomUUID());
  const lastSubmittedFingerprintRef = useRef<string | null>(null);
  // State, not a ref: written from `goToReview`, which is passed inline to
  // `handleSubmit()` in the JSX below -- a function constructed during
  // render must never write a ref (React Compiler safety rule; see the
  // identical note in LeafyHarvestForm.tsx/DispatchForm.tsx).
  const [reviewedLotIdsKey, setReviewedLotIdsKey] = useState<string | null>(null);
  const initial = nowDateAndTime();
  const cropId = lots[0]?.crop.id;
  const hasCounts = lots.some((l) => l.original_received_whole_unit_count != null);

  const [packSpecificationId, setPackSpecificationId] = useState("");
  const specsQuery = usePackSpecifications(cropId);
  const versionsQuery = usePackSpecificationVersions(packSpecificationId || null);

  const {
    register, control, handleSubmit, getValues, setValue, watch, formState: { errors },
  } = useForm<RecordPackingFormValues>({
    resolver: zodResolver(recordPackingFormSchema),
    defaultValues: {
      pack_specification_version_id: "",
      pack_specification_label: "",
      effective_date: initial.date,
      effective_time_of_day: initial.time,
      finished_goods_lot_code: "",
      package_count: 1,
      packed_output_weight_kg: 0,
      process_loss_weight_kg: 0,
      rejected_weight_kg: 0,
      note: "",
      count_mode: hasCounts,
      input_lines: lots.map((lot) => ({
        graded_produce_lot_id: lot.id,
        graded_produce_lot_code: lot.code,
        available_weight_kg: 0,
        available_whole_unit_count: null,
        consumed_weight_kg: 0,
        consumed_whole_unit_count: hasCounts ? 0 : undefined,
        note: "",
      })),
    },
    mode: "onBlur",
  });
  const { fields, append, remove } = useFieldArray({ control, name: "input_lines" });
  const lotIdsKey = lots.map((l) => l.id).join(",");

  // Reconcile `input_lines` to the current `lots` prop by id, in place --
  // never a full reset. Removals first (by index, high-to-low would also
  // work but RHF's `remove` accepts the whole index array at once), then
  // append exactly the Lots not already represented.
  useEffect(() => {
    const propIds = lots.map((l) => l.id);
    const current = getValues("input_lines");
    const removeIndices = current.reduce<number[]>((acc, line, idx) => {
      if (!propIds.includes(line.graded_produce_lot_id)) acc.push(idx);
      return acc;
    }, []);
    if (removeIndices.length > 0) remove(removeIndices);
    const remainingIds = current
      .filter((_, idx) => !removeIndices.includes(idx))
      .map((line) => line.graded_produce_lot_id);
    for (const lot of lots) {
      if (remainingIds.includes(lot.id)) continue;
      append({
        graded_produce_lot_id: lot.id,
        graded_produce_lot_code: lot.code,
        available_weight_kg: 0,
        available_whole_unit_count: null,
        consumed_weight_kg: 0,
        consumed_whole_unit_count: hasCounts ? 0 : undefined,
        note: "",
      });
    }
    // Keyed on the id set/order, not the `lots` array reference (a new
    // reference on every parent render) or `hasCounts`/`getValues`/`append`/
    // `remove` (stable across renders for a given `control`) -- this must
    // run only when the actual selected Lots change.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lotIdsKey]);

  const lotById = useMemo(() => new Map(lots.map((lot) => [lot.id, lot])), [lots]);

  const [prevServerError, setPrevServerError] = useState(serverError);
  if (serverError !== prevServerError) {
    setPrevServerError(serverError);
    if (serverError?.kind === "conflict") setStep("configure");
  }

  const watched = watch();
  const consumedSum = watched.input_lines.reduce((sum, l) => sum + (l.consumed_weight_kg || 0), 0);
  // PRE-COMMIT CORRECTION: same rationale as `GradingForm`'s own
  // `effectiveTimeIso` -- recomputed on every render from the watched
  // Date/Time fields so the Pack Specification Version picker below always
  // filters against the transaction's current effective time.
  const effectiveTimeIso = (() => {
    if (!watched.effective_date || !watched.effective_time_of_day) return "";
    const parsed = new Date(`${watched.effective_date}T${watched.effective_time_of_day}`);
    return Number.isNaN(parsed.getTime()) ? "" : parsed.toISOString();
  })();
  const selectableVersions = selectableVersionsAt(versionsQuery.data ?? [], effectiveTimeIso);
  const selectedVersionId = watch("pack_specification_version_id");

  useEffect(() => {
    if (!selectedVersionId) return;
    const stillSelectable = selectableVersionsAt(versionsQuery.data ?? [], effectiveTimeIso).some(
      (v) => v.id === selectedVersionId,
    );
    if (stillSelectable) return;
    setValue("pack_specification_version_id", "");
    setValue("pack_specification_label", "");
    // Clearing the selection above sets `selectedVersionId` to "" on the
    // next render, which re-runs this effect once more and immediately
    // returns via the guard at the top -- never a loop.
  }, [effectiveTimeIso, versionsQuery.data, selectedVersionId, setValue]);

  // PILOT-UX-003: never show a stale Review -- if the selected-Lot set
  // changes while the operator is on Review (the source panel below stays
  // interactive throughout), drop back to Configure so the operator
  // re-confirms against the current selection rather than reviewing/
  // submitting a snapshot that no longer matches it. Adjusted directly
  // during render (React's own blessed pattern) rather than in an effect,
  // which would cause an extra, avoidable cascading render.
  const [prevLotIdsKeyForStaleCheck, setPrevLotIdsKeyForStaleCheck] = useState(lotIdsKey);
  if (lotIdsKey !== prevLotIdsKeyForStaleCheck) {
    setPrevLotIdsKeyForStaleCheck(lotIdsKey);
    if (step === "review" && reviewedLotIdsKey !== null && reviewedLotIdsKey !== lotIdsKey) {
      setStep("configure");
    }
  }

  function goToReview(values: RecordPackingFormValues) {
    void values;
    setReviewedLotIdsKey(lotIdsKey);
    setStep("review");
  }

  function confirm() {
    const values = getValues();
    const effectiveTime = new Date(`${values.effective_date}T${values.effective_time_of_day}`).toISOString();
    const inputLines = values.input_lines.map((l) => ({
      graded_produce_lot_id: l.graded_produce_lot_id,
      consumed_weight_kg: String(l.consumed_weight_kg),
      consumed_whole_unit_count: values.count_mode ? l.consumed_whole_unit_count ?? null : null,
      note: l.note.trim() || null,
    }));
    const fingerprint = JSON.stringify({ values, inputLines });
    let idToUse = clientCommandId;
    if (lastSubmittedFingerprintRef.current !== null && lastSubmittedFingerprintRef.current !== fingerprint) {
      idToUse = crypto.randomUUID();
      setClientCommandId(idToUse);
    }
    lastSubmittedFingerprintRef.current = fingerprint;
    const payload: PackingEventCreate = {
      client_command_id: idToUse,
      pack_specification_version_id: values.pack_specification_version_id,
      effective_time: effectiveTime,
      finished_goods_lot_code: values.finished_goods_lot_code.trim().toUpperCase(),
      package_count: values.package_count,
      packed_output_weight_kg: String(values.packed_output_weight_kg),
      process_loss_weight_kg: String(values.process_loss_weight_kg),
      rejected_weight_kg: String(values.rejected_weight_kg),
      note: values.note.trim() || null,
      input_lines: inputLines,
    };
    onSubmit(payload);
  }

  if (step === "review") {
    const values = getValues();
    return (
      <div className="flex flex-col gap-4 rounded-xl border border-border-subtle bg-surface p-4">
        <StepIndicator step="review" />
        <h2 className="font-serif text-base font-semibold text-ink">Review before recording</h2>
        <p className="text-sm text-ink-muted">
          {values.finished_goods_lot_code} · {values.pack_specification_label} · {values.effective_date}{" "}
          {values.effective_time_of_day}
        </p>
        <ReconciliationSummary
          inputLabel="Total consumed input"
          inputValue={consumedSum}
          unit="kg"
          parts={[
            { label: "Packed output", value: values.packed_output_weight_kg },
            { label: "Process loss", value: values.process_loss_weight_kg },
            { label: "Rejected", value: values.rejected_weight_kg },
          ]}
        />
        <ul className="flex flex-col gap-2">
          {values.input_lines.map((l) => (
            <li key={l.graded_produce_lot_id} className="rounded-md border border-border-subtle p-3 text-sm">
              <span className="font-medium text-ink">{l.graded_produce_lot_code}</span>{" "}
              <span className="text-ink-muted">
                — {l.consumed_weight_kg} kg{values.count_mode ? ` / ${l.consumed_whole_unit_count ?? "—"} units` : ""}
              </span>
            </li>
          ))}
        </ul>
        <p className="text-sm text-ink">Packages: {values.package_count}</p>
        {values.note && (
          <p className="text-sm text-ink-muted">
            Note: <span className="text-ink">{values.note}</span>
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
      className="flex flex-col gap-4 rounded-xl border border-border-subtle bg-surface p-4"
    >
      <StepIndicator step="configure" />
      <h2 className="font-serif text-base font-semibold text-ink">Pack {lots.map((l) => l.code).join(", ")}</h2>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2 lg:items-start">
        <div>
          <h3 className="mb-2 text-sm font-semibold text-ink">Input Graded Produce Lots</h3>
          <ul className="flex flex-col gap-2">
            {fields.map((field, index) => {
              const lot = lotById.get(field.graded_produce_lot_id);
              if (!lot) return null;
              return (
                <PackingInputLineRow
                  key={field.id}
                  farmId={farmId}
                  lot={lot}
                  index={index}
                  register={register}
                  setValue={setValue}
                  watch={watch}
                  errors={errors}
                  onRemove={() => onRemoveLot(lot.id)}
                  removable
                />
              );
            })}
          </ul>
          {typeof errors.input_lines?.message === "string" && <p className={errorClass}>{errors.input_lines.message}</p>}
          {errors.input_lines?.root && <p className={errorClass}>{errors.input_lines.root.message}</p>}
        </div>

        <div className="flex flex-col gap-3">
          <h3 className="text-sm font-semibold text-ink">Packed Output</h3>
          <fieldset className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <label className="flex flex-col gap-1">
              <span className={labelClass}>Pack Specification</span>
              <select
                className={inputClass}
                value={packSpecificationId}
                onChange={(e) => {
                  setPackSpecificationId(e.target.value);
                  setValue("pack_specification_version_id", "");
                  setValue("pack_specification_label", "");
                }}
              >
                <option value="">Select a Pack Specification…</option>
                {(specsQuery.data ?? []).map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name}
                  </option>
                ))}
              </select>
            </label>
            {/* The error/hint below are deliberately siblings of the <label>,
                not nested inside it -- see `GradingOutputRow`'s own identical
                note (folding them into the select's accessible name is wrong
                for assistive tech and breaks exact-match label queries). */}
            <div className="flex flex-col gap-1">
              <label className="flex flex-col gap-1">
                <span className={labelClass}>Version</span>
                <select
                  className={inputClass}
                  disabled={!packSpecificationId}
                  {...register("pack_specification_version_id", {
                    onChange: (e) => {
                      const version = selectableVersions.find((v) => v.id === e.target.value);
                      const specName = (specsQuery.data ?? []).find((s) => s.id === packSpecificationId)?.name ?? "";
                      setValue(
                        "pack_specification_label",
                        version ? `${specName} v${version.version_number}` : "",
                      );
                    },
                  })}
                >
                  <option value="">{packSpecificationId ? "Select a version…" : "Select a specification first"}</option>
                  {selectableVersions.map((v) => (
                    <option key={v.id} value={v.id}>
                      v{v.version_number}
                      {v.nominal_net_weight_kg ? ` — nominal ${v.nominal_net_weight_kg} kg` : ""}
                      {v.whole_units_per_pack ? ` / ${v.whole_units_per_pack} units` : ""}
                    </option>
                  ))}
                </select>
              </label>
              {errors.pack_specification_version_id?.message && (
                <span className={errorClass}>{errors.pack_specification_version_id.message}</span>
              )}
              {packSpecificationId && selectableVersions.length === 0 && (versionsQuery.data?.length ?? 0) > 0 && (
                <span className="text-xs text-ink-muted">
                  No version of this Pack Specification is valid at the selected effective time.
                </span>
              )}
            </div>
          </fieldset>

          <fieldset className="grid grid-cols-2 gap-3">
            <Field label="Finished Goods Lot code" error={errors.finished_goods_lot_code?.message}>
              <input className={inputClass} {...register("finished_goods_lot_code")} />
            </Field>
            <Field label="Package count" error={errors.package_count?.message}>
              <input type="number" min={1} step={1} className={inputClass} {...register("package_count", { valueAsNumber: true })} />
            </Field>
            <Field label="Packed output weight (kg)" error={errors.packed_output_weight_kg?.message}>
              <input
                type="number" min={0.001} step={0.001} className={inputClass}
                {...register("packed_output_weight_kg", { valueAsNumber: true })}
              />
            </Field>
            <Field label="Process loss (kg)" error={errors.process_loss_weight_kg?.message}>
              <input type="number" min={0} step={0.001} className={inputClass} {...register("process_loss_weight_kg", { valueAsNumber: true })} />
            </Field>
            <Field label="Rejected (kg)" error={errors.rejected_weight_kg?.message}>
              <input type="number" min={0} step={0.001} className={inputClass} {...register("rejected_weight_kg", { valueAsNumber: true })} />
            </Field>
          </fieldset>
        </div>
      </div>

      <ReconciliationSummary
        inputLabel="Total consumed input"
        inputValue={consumedSum}
        unit="kg"
        parts={[
          { label: "Packed output", value: watched.packed_output_weight_kg || 0 },
          { label: "Process loss", value: watched.process_loss_weight_kg || 0 },
          { label: "Rejected", value: watched.rejected_weight_kg || 0 },
        ]}
      />

      <Field label="Note (optional)" error={errors.note?.message}>
        <textarea className={`${inputClass} min-h-20`} rows={2} {...register("note")} />
      </Field>

      <fieldset className="grid grid-cols-2 gap-3">
        <Field label="Date" error={errors.effective_date?.message}>
          <input type="date" className={inputClass} {...register("effective_date")} />
        </Field>
        <Field label="Time" error={errors.effective_time_of_day?.message}>
          <input type="time" className={inputClass} {...register("effective_time_of_day")} />
        </Field>
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
