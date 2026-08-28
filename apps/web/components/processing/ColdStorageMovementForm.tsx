"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useRef, useState } from "react";
import { useForm } from "react-hook-form";

import { LocationSelect } from "@/components/processing/LocationSelect";
import type { FinishedGoodsLotRead, FinishedGoodsStorageMovementCreate, LocationTreeNode } from "@/lib/api/client";
import { AppError, friendlyMutationErrorMessage } from "@/lib/errors/adapter";
import { useFinishedGoodsPlacement } from "@/lib/query/hooks";
import { MOVEMENT_KINDS, recordStorageMovementFormSchema, type RecordStorageMovementFormValues } from "@/lib/validation/coldStorage";

const inputClass =
  "min-h-11 w-full rounded-md border border-border-subtle bg-surface px-3 text-sm text-ink focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-600";
const labelClass = "block text-sm font-medium text-ink";
const errorClass = "text-xs text-red-700";

const KIND_LABELS: Record<(typeof MOVEMENT_KINDS)[number], string> = {
  place: "Place into Cold Storage",
  release: "Release out of Cold Storage",
  transfer: "Transfer between locations",
};

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

/** PILOT-READY-001: "Record Cold Storage Movement" -- place a Finished
 * Goods Lot into Cold Storage, release it back out, or transfer it between
 * locations. Backend contract requires PLACE to carry only a destination
 * and RELEASE only a source (`FinishedGoodsStorageMovementCreate`'s own
 * kind-specific model validator) -- the form's field visibility mirrors
 * that exactly rather than always showing both. Single-step (no
 * configure -> review split, unlike Packing/Grading/Dispatch): this
 * command has no reconciliation math and no multi-line shape to preview. */
export function ColdStorageMovementForm({
  farmId,
  lot,
  locations,
  onSubmit,
  isSubmitting,
  serverError,
}: {
  farmId: string;
  lot: FinishedGoodsLotRead;
  locations: LocationTreeNode[];
  onSubmit: (payload: FinishedGoodsStorageMovementCreate) => void;
  isSubmitting: boolean;
  serverError?: AppError | null;
}) {
  const [clientCommandId, setClientCommandId] = useState(() => crypto.randomUUID());
  const lastSubmittedFingerprintRef = useRef<string | null>(null);
  const initial = nowDateAndTime();
  const placementQuery = useFinishedGoodsPlacement(farmId, lot.id);

  const {
    register, handleSubmit, watch, setValue, formState: { errors },
  } = useForm<RecordStorageMovementFormValues>({
    resolver: zodResolver(recordStorageMovementFormSchema),
    defaultValues: {
      finished_goods_lot_id: lot.id,
      movement_kind: "place",
      source_location_id: "",
      destination_location_id: "",
      moved_weight_kg: 0,
      moved_package_count: 0,
      effective_date: initial.date,
      effective_time_of_day: initial.time,
      note: "",
    },
    mode: "onBlur",
  });

  const kind = watch("movement_kind");

  function submit(values: RecordStorageMovementFormValues) {
    const effectiveTime = new Date(`${values.effective_date}T${values.effective_time_of_day}`).toISOString();
    const basePayload = {
      effective_time: effectiveTime,
      finished_goods_lot_id: lot.id,
      movement_kind: values.movement_kind,
      source_location_id: values.movement_kind === "place" ? null : values.source_location_id || null,
      destination_location_id: values.movement_kind === "release" ? null : values.destination_location_id || null,
      moved_weight_kg: String(values.moved_weight_kg),
      moved_package_count: values.moved_package_count,
      note: values.note.trim() || null,
    };
    const fingerprint = JSON.stringify(basePayload);
    let idToUse = clientCommandId;
    if (lastSubmittedFingerprintRef.current !== null && lastSubmittedFingerprintRef.current !== fingerprint) {
      idToUse = crypto.randomUUID();
      setClientCommandId(idToUse);
    }
    lastSubmittedFingerprintRef.current = fingerprint;
    const payload: FinishedGoodsStorageMovementCreate = { ...basePayload, client_command_id: idToUse };
    onSubmit(payload);
  }

  return (
    <form
      onSubmit={handleSubmit(submit)}
      className="flex flex-col gap-4 rounded-lg border border-border-subtle bg-surface p-4"
    >
      <h2 className="text-sm font-semibold text-ink">Cold Storage — {lot.code}</h2>
      <p className="text-xs text-ink-muted">
        {placementQuery.data
          ? `Available ${placementQuery.data.available_weight_kg} kg — Placed ${placementQuery.data.total_placed_weight_kg} kg — Unplaced ${placementQuery.data.unplaced_weight_kg} kg`
          : "Loading current placement…"}
      </p>

      <Field label="Movement" error={errors.movement_kind?.message}>
        <select className={inputClass} {...register("movement_kind")}>
          {MOVEMENT_KINDS.map((k) => (
            <option key={k} value={k}>
              {KIND_LABELS[k]}
            </option>
          ))}
        </select>
      </Field>

      {(kind === "release" || kind === "transfer") && (
        <Field label="Source location" error={errors.source_location_id?.message}>
          <LocationSelect
            nodes={locations}
            value={watch("source_location_id")}
            onChange={(id) => setValue("source_location_id", id)}
          />
        </Field>
      )}
      {(kind === "place" || kind === "transfer") && (
        <Field label="Destination location" error={errors.destination_location_id?.message}>
          <LocationSelect
            nodes={locations}
            value={watch("destination_location_id")}
            onChange={(id) => setValue("destination_location_id", id)}
          />
        </Field>
      )}

      <fieldset className="grid grid-cols-2 gap-3">
        <Field label="Weight (kg)" error={errors.moved_weight_kg?.message}>
          <input type="number" min={0.001} step={0.001} className={inputClass} {...register("moved_weight_kg", { valueAsNumber: true })} />
        </Field>
        <Field label="Package count" error={errors.moved_package_count?.message}>
          <input type="number" min={1} step={1} className={inputClass} {...register("moved_package_count", { valueAsNumber: true })} />
        </Field>
      </fieldset>

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
        <button
          type="submit"
          disabled={isSubmitting}
          className="min-h-11 rounded-md bg-brand-700 px-4 text-sm font-medium text-white hover:bg-brand-800 disabled:opacity-60"
        >
          {isSubmitting ? "Recording…" : "Record Movement"}
        </button>
      </div>
    </form>
  );
}
