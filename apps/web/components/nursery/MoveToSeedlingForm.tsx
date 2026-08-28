"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { useForm } from "react-hook-form";

import { Button } from "@/components/ui/Button";
import type { SeedlingEntryCreate } from "@/lib/api/client";
import { useAvailableSeedlingTables, useSeedlingCandidateTrays } from "@/lib/query/hooks";
import {
  DEFAULT_SEEDLING_ENTRY_FORM_VALUES,
  buildSeedlingEntryPayload,
  seedlingEntryFormSchema,
  type SeedlingEntryFormValues,
} from "@/lib/validation/seedlingEntry";

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

/** NURSERY-OPS-003A: atomically pairs a physical Movement (Trolley Slot ->
 * Seedling Table) with an immutable frozen biological handoff referencing
 * the historically-valid completed Germination outcome -- ONE operator
 * command, ONE atomic backend transaction. Only Trays in state
 * `ready_for_seedling` (a completed Germination handoff exists, no
 * SeedlingEntry yet, not currently on a Seedling Table) are offered here;
 * a Tray with no completed handoff cannot be selected -- no provisional
 * count, Seeds Sown, or Sown Sites is ever substituted (section 41). */
export function MoveToSeedlingForm({
  farmId, onSubmit, onCancel, isSubmitting, serverError,
}: {
  farmId: string;
  onSubmit: (payload: SeedlingEntryCreate) => void;
  onCancel: () => void;
  isSubmitting: boolean;
  serverError?: string | null;
}) {
  const [step, setStep] = useState<"configure" | "review">("configure");
  const [clientCommandId] = useState(() => crypto.randomUUID());
  const [selectedAssignmentId, setSelectedAssignmentId] = useState("");

  const initial = nowDateAndTime();
  const {
    register, setValue, trigger, getValues, formState: { errors },
  } = useForm<SeedlingEntryFormValues>({
    resolver: zodResolver(seedlingEntryFormSchema),
    defaultValues: { ...DEFAULT_SEEDLING_ENTRY_FORM_VALUES, effective_date: initial.date, effective_time_of_day: initial.time },
    mode: "onBlur",
  });

  const traysQuery = useSeedlingCandidateTrays(farmId);
  const eligibleTrays = (traysQuery.data ?? []).filter((t) => t.state === "ready_for_seedling");
  const tablesQuery = useAvailableSeedlingTables(farmId);
  const tables = (tablesQuery.data ?? []).filter((t) => t.remaining_capacity > 0);

  const selectedTray = eligibleTrays.find((t) => t.batch_carrier_assignment_id === selectedAssignmentId);

  async function goToReview() {
    const valid = await trigger();
    if (valid) setStep("review");
  }

  function submitReview() {
    onSubmit(buildSeedlingEntryPayload(getValues(), clientCommandId));
  }

  if (step === "review") {
    const values = getValues();
    const tray = eligibleTrays.find((t) => t.batch_carrier_assignment_id === values.batch_carrier_assignment_id);
    const table = tables.find((t) => t.id === values.destination_seedling_table_id);
    const living = tray?.germination_handoff?.living_seedling_count ?? null;
    return (
      <div className="flex flex-col gap-4">
        <div className="flex flex-col gap-4 rounded-xl border border-border-subtle bg-surface p-4">
          <h2 className="font-serif text-base font-semibold text-ink">Review before moving to Seedling</h2>
          <p className="text-sm text-ink-muted">
            This entry will establish {living?.toLocaleString() ?? "—"} living seedlings as the starting Seedling
            quantity for this Tray and move it to {table?.code ?? "the selected Table"}.
          </p>
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
              <dt className="text-ink-muted">Normal seedlings</dt>
              <dd className="font-medium text-ink">{tray?.germination_handoff?.normal_seedling_count.toLocaleString()}</dd>
            </div>
            <div>
              <dt className="text-ink-muted">Abnormal seedlings</dt>
              <dd className="font-medium text-ink">{tray?.germination_handoff?.abnormal_seedling_count.toLocaleString()}</dd>
            </div>
            <div>
              <dt className="text-ink-muted">Living seedlings</dt>
              <dd className="font-medium text-ink">{living?.toLocaleString()}</dd>
            </div>
            <div>
              <dt className="text-ink-muted">Destination Table</dt>
              <dd className="font-medium text-ink">{table?.code}</dd>
            </div>
            <div>
              <dt className="text-ink-muted">Table remaining slots</dt>
              <dd className="font-medium text-ink">{table?.remaining_capacity}</dd>
            </div>
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
            {isSubmitting ? "Moving…" : "Move to Seedling"}
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
          <p className="text-sm text-ink-muted">
            No Seed Trays are ready for Seedling. Complete the Germination assessment first.
          </p>
        ) : (
          <Field label="Seed Tray" error={errors.batch_carrier_assignment_id?.message}>
            <select
              {...register("batch_carrier_assignment_id")}
              onChange={(e) => {
                setValue("batch_carrier_assignment_id", e.target.value);
                setSelectedAssignmentId(e.target.value);
              }}
              className={inputClass}
            >
              <option value="">Select a Seed Tray…</option>
              {eligibleTrays.map((t) => (
                <option key={t.batch_carrier_assignment_id} value={t.batch_carrier_assignment_id}>
                  {t.batch_code} — {t.tray.code} ({t.germination_handoff?.living_seedling_count.toLocaleString()} living)
                </option>
              ))}
            </select>
          </Field>
        )}
        {selectedTray && (
          <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm sm:grid-cols-3">
            <div>
              <dt className="text-ink-muted">Crop / Variety</dt>
              <dd className="font-medium text-ink">
                {selectedTray.seed_lot.crop.common_name} / {selectedTray.seed_lot.variety.name}
              </dd>
            </div>
            <div>
              <dt className="text-ink-muted">Seed Lot</dt>
              <dd className="font-medium text-ink">{selectedTray.seed_lot.code}</dd>
            </div>
            <div>
              <dt className="text-ink-muted">Living seedlings (completed handoff)</dt>
              <dd className="font-medium text-ink">
                {selectedTray.germination_handoff?.living_seedling_count.toLocaleString()}
              </dd>
            </div>
          </dl>
        )}
      </fieldset>

      {selectedTray && (
        <>
          <fieldset className="flex flex-col gap-4 rounded-xl border border-border-subtle bg-surface p-4">
            <legend className="px-1 text-sm font-semibold text-ink">Seedling Table</legend>
            {tablesQuery.isSuccess && tables.length === 0 ? (
              <p className="text-sm text-ink-muted">No Seedling Tables have available capacity.</p>
            ) : (
              <Field label="Seedling Table" error={errors.destination_seedling_table_id?.message}>
                <select {...register("destination_seedling_table_id")} className={inputClass}>
                  <option value="">Select a Seedling Table…</option>
                  {tables.map((t) => (
                    <option key={t.id} value={t.id}>
                      {t.code} — {t.seedling_area.name} ({t.remaining_capacity} of {t.capacity ?? 1} slots free)
                    </option>
                  ))}
                </select>
              </Field>
            )}
          </fieldset>

          <fieldset className="grid grid-cols-1 gap-4 rounded-xl border border-border-subtle bg-surface p-4 sm:grid-cols-2">
            <legend className="px-1 text-sm font-semibold text-ink">Entry date/time</legend>
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
        </>
      )}

      <div className="flex gap-3">
        <Button type="button" variant="secondary" onClick={onCancel}>
          Cancel
        </Button>
        <Button type="submit" variant="primary" disabled={!selectedTray}>
          Review
        </Button>
      </div>
    </form>
  );
}
