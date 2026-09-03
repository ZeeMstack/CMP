"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { useForm } from "react-hook-form";

import { Button } from "@/components/ui/Button";
import type { PlaceTrayCreate } from "@/lib/api/client";
import { useAvailableTrolleys, useGerminationTrays, useTrolleyLevels } from "@/lib/query/hooks";
import {
  DEFAULT_PLACE_TRAY_FORM_VALUES,
  buildPlaceTrayPayload,
  placeTrayFormSchema,
  type PlaceTrayFormValues,
} from "@/lib/validation/germination";

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

/** A Sown Seed Tray into a Level on a Trolley that is currently placed in a
 * Germination Chamber (enforced server-side -- the backend rejects a
 * Trolley that isn't currently in Germination, section 16).
 *
 * PILOT-UX-001B: the backend is authoritative for per-Level classification
 * (`legacy` / `direct` / `invalid`, via `useTrolleyLevels`) -- this form
 * consumes `mode` and never re-derives it from raw position structure.
 * A `direct` Level is itself the terminal selection (its own id is
 * submitted, no further step). A `legacy` Level still requires picking one
 * of its open child Slots, exactly as before. An `invalid` Level (or a
 * Level with zero remaining capacity) is shown, disabled, so an operator
 * can see it exists and why it cannot be used, but can never select it.
 *
 * Physical placement only; no biological Germination outcome field appears
 * here. */
export function MoveTrayForm({
  farmId, onSubmit, onCancel, isSubmitting, serverError,
}: {
  farmId: string;
  onSubmit: (payload: PlaceTrayCreate) => void;
  onCancel: () => void;
  isSubmitting: boolean;
  serverError?: string | null;
}) {
  const [step, setStep] = useState<"configure" | "review">("configure");
  const [clientCommandId] = useState(() => crypto.randomUUID());
  const [selectedTrolleyId, setSelectedTrolleyId] = useState("");
  const [selectedLevelId, setSelectedLevelId] = useState("");

  const initial = nowDateAndTime();
  const {
    register, setValue, trigger, getValues, formState: { errors },
  } = useForm<PlaceTrayFormValues>({
    resolver: zodResolver(placeTrayFormSchema),
    defaultValues: { ...DEFAULT_PLACE_TRAY_FORM_VALUES, effective_date: initial.date, effective_time_of_day: initial.time },
    mode: "onBlur",
  });

  const traysQuery = useGerminationTrays(farmId);
  const eligibleTrays = (traysQuery.data ?? []).filter((t) => t.state !== "in_germination");
  const trolleysQuery = useAvailableTrolleys(farmId);
  const trolleys = trolleysQuery.data ?? [];
  const levelsQuery = useTrolleyLevels(farmId, selectedTrolleyId);
  const levels = levelsQuery.data ?? [];
  const selectedLevel = levels.find((lvl) => lvl.id === selectedLevelId) ?? null;
  const openSlots = selectedLevel?.mode === "legacy" ? selectedLevel.slots.filter((s) => !s.occupied) : [];

  async function goToReview() {
    const valid = await trigger();
    if (valid) setStep("review");
  }

  function submitReview() {
    onSubmit(buildPlaceTrayPayload(getValues(), clientCommandId));
  }

  function handleLevelChange(levelId: string) {
    setSelectedLevelId(levelId);
    const level = levels.find((lvl) => lvl.id === levelId);
    // A `direct` Level is itself the terminal target -- submit its own id
    // immediately. A `legacy` Level still needs a Slot choice below, so its
    // target starts blank; an `invalid`/full Level is never selectable (its
    // `<option>` is disabled), so this branch is unreachable for it.
    setValue("asset_position_id", level?.mode === "direct" ? level.id : "");
  }

  if (step === "review") {
    const values = getValues();
    const tray = eligibleTrays.find((t) => t.tray.id === values.tray_id);
    const trolley = trolleys.find((t) => t.id === values.trolley_id);
    const slot = selectedLevel?.mode === "legacy" ? openSlots.find((s) => s.id === values.asset_position_id) : null;
    return (
      <div className="flex flex-col gap-4">
        <div className="flex flex-col gap-4 rounded-xl border border-border-subtle bg-surface p-4">
          <h2 className="font-serif text-base font-semibold text-ink">Review before moving</h2>
          <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm sm:grid-cols-3">
            <div>
              <dt className="text-ink-muted">Batch</dt>
              <dd className="font-medium text-ink">{tray?.batch_code}</dd>
            </div>
            <div>
              <dt className="text-ink-muted">Seed Tray</dt>
              <dd className="font-medium text-ink">{tray?.tray.code}</dd>
            </div>
            <div>
              <dt className="text-ink-muted">Seeds sown</dt>
              <dd className="font-medium text-ink">{tray?.seeds_sown.toLocaleString()}</dd>
            </div>
            <div>
              <dt className="text-ink-muted">Trolley</dt>
              <dd className="font-medium text-ink">{trolley?.code}</dd>
            </div>
            <div>
              <dt className="text-ink-muted">Germination Chamber</dt>
              <dd className="font-medium text-ink">{trolley?.chamber.code}</dd>
            </div>
            <div>
              <dt className="text-ink-muted">Level</dt>
              <dd className="font-medium text-ink">{selectedLevel?.code}</dd>
            </div>
            {selectedLevel?.mode === "legacy" && (
              <div>
                <dt className="text-ink-muted">Slot</dt>
                <dd className="font-medium text-ink">{slot?.code}</dd>
              </div>
            )}
            <div>
              <dt className="text-ink-muted">Occurred at</dt>
              <dd className="font-medium text-ink">
                {values.effective_date} {values.effective_time_of_day}
              </dd>
            </div>
          </dl>
        </div>
        {serverError && <p role="alert" className={errorClass}>{serverError}</p>}
        <div className="flex gap-3">
          <Button type="button" variant="secondary" onClick={() => setStep("configure")} disabled={isSubmitting}>
            Back
          </Button>
          <Button type="button" variant="primary" onClick={submitReview} disabled={isSubmitting}>
            {isSubmitting ? "Moving…" : "Move to Germination"}
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
      <fieldset className="flex flex-col gap-4 rounded-xl border border-border-subtle bg-surface p-4">
        <legend className="px-1 text-sm font-semibold text-ink">Seed Tray</legend>
        {traysQuery.isSuccess && eligibleTrays.length === 0 ? (
          <p className="text-sm text-ink-muted">No Seed Trays are awaiting Germination placement.</p>
        ) : (
          <Field label="Seed Tray" error={errors.tray_id?.message}>
            <select {...register("tray_id")} className={inputClass}>
              <option value="">Select a Seed Tray…</option>
              {eligibleTrays.map((t) => (
                <option key={t.tray.id} value={t.tray.id}>
                  {t.batch_code} — {t.tray.code} ({t.seeds_sown} seeds)
                </option>
              ))}
            </select>
          </Field>
        )}
      </fieldset>

      <fieldset className="flex flex-col gap-4 rounded-xl border border-border-subtle bg-surface p-4">
        <legend className="px-1 text-sm font-semibold text-ink">Trolley / Level</legend>
        {trolleysQuery.isSuccess && trolleys.length === 0 ? (
          <p className="text-sm text-ink-muted">
            No Trolleys are currently placed in a Germination Chamber. Place a Trolley first.
          </p>
        ) : (
          <>
            <Field label="Trolley" error={errors.trolley_id?.message}>
              <select
                {...register("trolley_id")}
                className={inputClass}
                onChange={(e) => {
                  setValue("trolley_id", e.target.value);
                  setSelectedTrolleyId(e.target.value);
                  setSelectedLevelId("");
                  setValue("asset_position_id", "");
                }}
              >
                <option value="">Select a Trolley…</option>
                {trolleys.map((trolley) => (
                  <option key={trolley.id} value={trolley.id}>
                    {trolley.code} — {trolley.chamber.code} ({trolley.available_capacity} of{" "}
                    {trolley.total_capacity} free)
                  </option>
                ))}
              </select>
            </Field>
            {selectedTrolleyId && (
              <Field label="Level" error={errors.asset_position_id?.message}>
                <select
                  value={selectedLevelId}
                  onChange={(e) => handleLevelChange(e.target.value)}
                  className={inputClass}
                >
                  <option value="">Select a Level…</option>
                  {levels.map((level) => {
                    const isFull = level.mode !== "invalid" && (level.available_capacity ?? 0) <= 0;
                    const disabled = level.mode === "invalid" || isFull;
                    const suffix =
                      level.mode === "invalid"
                        ? " (not configured)"
                        : isFull
                          ? " (full)"
                          : level.mode === "direct"
                            ? ` (${level.available_capacity} of ${level.capacity} free)`
                            : ` (${level.available_capacity} slot${level.available_capacity === 1 ? "" : "s"} free)`;
                    return (
                      <option key={level.id} value={level.id} disabled={disabled}>
                        {level.code}
                        {suffix}
                      </option>
                    );
                  })}
                </select>
              </Field>
            )}
            {selectedLevel?.mode === "legacy" && (
              <Field label="Slot" error={errors.asset_position_id?.message}>
                <select {...register("asset_position_id")} className={inputClass}>
                  <option value="">Select a Slot…</option>
                  {openSlots.map((slot) => (
                    <option key={slot.id} value={slot.id}>
                      {slot.code}
                    </option>
                  ))}
                </select>
              </Field>
            )}
          </>
        )}
      </fieldset>

      <fieldset className="grid grid-cols-1 gap-4 rounded-xl border border-border-subtle bg-surface p-4 sm:grid-cols-2">
        <legend className="px-1 text-sm font-semibold text-ink">Placement date/time</legend>
        <Field label="Date" error={errors.effective_date?.message}>
          <input type="date" {...register("effective_date")} className={inputClass} />
        </Field>
        <Field label="Time" error={errors.effective_time_of_day?.message}>
          <input type="time" {...register("effective_time_of_day")} className={inputClass} />
        </Field>
      </fieldset>

      <fieldset className="flex flex-col gap-4 rounded-xl border border-border-subtle bg-surface p-4">
        <legend className="px-1 text-sm font-semibold text-ink">Reason (optional)</legend>
        <textarea {...register("reason")} className={`${inputClass} min-h-20`} rows={2} />
      </fieldset>

      <div className="flex gap-3">
        <Button type="button" variant="secondary" onClick={onCancel}>
          Cancel
        </Button>
        <Button type="submit" variant="primary">
          Review
        </Button>
      </div>
    </form>
  );
}
