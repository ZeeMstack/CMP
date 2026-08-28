"use client";

import { useEffect, useState } from "react";
import type { UseFormRegister, UseFormSetValue, UseFormWatch, FieldErrors } from "react-hook-form";

import { Button } from "@/components/ui/Button";
import { selectableVersionsAt } from "@/lib/format/versionLifecycle";
import { useGradeDefinitions, useGradeDefinitionVersions } from "@/lib/query/hooks";
import type { RecordGradingFormValues } from "@/lib/validation/grading";

const inputClass =
  "min-h-11 w-full rounded-md border border-border-subtle bg-surface px-3 text-sm text-ink focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-600";
const labelClass = "block text-xs font-medium text-ink-muted";
const errorClass = "text-xs text-red-700";

/** POSTHARVEST-OPS-001G: one Graded Produce Lot output line inside the
 * Grading form. Picking a grade is two cascading reads (Grade Definition ->
 * its Versions, see `apps/api/app/api/grade_definitions.py` -- a Grading
 * output references a Version, not a Definition directly), so this is its
 * own component: each output row owns its own Definition/Version picker
 * state independently of the others, and mounting/unmounting a row (add/
 * remove output) never disturbs another row's cascade.
 *
 * PRE-COMMIT CORRECTION: the Version picker is filtered to what's
 * historically valid at the transaction's own `effectiveTimeIso` (DRAFT
 * never selectable; ACTIVE/RETIRED selectable inside their own
 * [effective_from, effective_until) window) -- never by current lifecycle
 * status alone. See `lib/format/versionLifecycle.ts`. Changing
 * `effectiveTimeIso` (the operator edits the Date/Time field) re-filters
 * this list and clears an already-selected Version that falls out of the
 * new window, so an invalid selection is never left silently in place. */
export function GradingOutputRow({
  cropId,
  index,
  effectiveTimeIso,
  register,
  setValue,
  watch,
  errors,
  onRemove,
  removable,
}: {
  cropId: string;
  index: number;
  effectiveTimeIso: string;
  register: UseFormRegister<RecordGradingFormValues>;
  setValue: UseFormSetValue<RecordGradingFormValues>;
  watch: UseFormWatch<RecordGradingFormValues>;
  errors: FieldErrors<RecordGradingFormValues>;
  onRemove: () => void;
  removable: boolean;
}) {
  const [definitionId, setDefinitionId] = useState("");
  const definitionsQuery = useGradeDefinitions(cropId);
  const versionsQuery = useGradeDefinitionVersions(definitionId || null);
  const selectableVersions = selectableVersionsAt(versionsQuery.data ?? [], effectiveTimeIso);
  const rowErrors = errors.outputs?.[index];
  const countMode = watch("count_mode");
  const selectedVersionId = watch(`outputs.${index}.grade_definition_version_id`);

  useEffect(() => {
    if (!selectedVersionId) return;
    const stillSelectable = selectableVersionsAt(versionsQuery.data ?? [], effectiveTimeIso).some(
      (v) => v.id === selectedVersionId,
    );
    if (stillSelectable) return;
    setValue(`outputs.${index}.grade_definition_version_id`, "");
    setValue(`outputs.${index}.grade_definition_label`, "");
    // Clearing the selection above sets `selectedVersionId` to "" on the
    // next render, which re-runs this effect once more and immediately
    // returns via the guard at the top -- never a loop.
  }, [effectiveTimeIso, versionsQuery.data, selectedVersionId, index, setValue]);

  return (
    <li className="rounded-md border border-border-subtle p-3">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <label className="flex flex-col gap-1">
          <span className={labelClass}>Grade</span>
          <select
            className={inputClass}
            value={definitionId}
            onChange={(e) => {
              setDefinitionId(e.target.value);
              setValue(`outputs.${index}.grade_definition_version_id`, "");
              setValue(`outputs.${index}.grade_definition_label`, "");
            }}
          >
            <option value="">Select a grade…</option>
            {(definitionsQuery.data ?? []).map((d) => (
              <option key={d.id} value={d.id}>
                {d.name}
              </option>
            ))}
          </select>
        </label>
        {/* The error/hint below are deliberately siblings of the <label>,
            not nested inside it -- inside, they'd be folded into the
            select's own accessible name (its label text), which is wrong
            for assistive tech and breaks exact-match label queries in
            tests. */}
        <div className="flex flex-col gap-1">
          <label className="flex flex-col gap-1">
            <span className={labelClass}>Version</span>
            <select
              className={inputClass}
              disabled={!definitionId}
              {...register(`outputs.${index}.grade_definition_version_id`, {
                onChange: (e) => {
                  const version = selectableVersions.find((v) => v.id === e.target.value);
                  const definitionName = (definitionsQuery.data ?? []).find((d) => d.id === definitionId)?.name ?? "";
                  setValue(
                    `outputs.${index}.grade_definition_label`,
                    version ? `${definitionName} v${version.version_number}` : "",
                  );
                },
              })}
            >
              <option value="">{definitionId ? "Select a version…" : "Select a grade first"}</option>
              {selectableVersions.map((v) => (
                <option key={v.id} value={v.id}>
                  v{v.version_number}
                  {v.spec_notes ? ` — ${v.spec_notes}` : ""}
                </option>
              ))}
            </select>
          </label>
          {rowErrors?.grade_definition_version_id && (
            <span className={errorClass}>{rowErrors.grade_definition_version_id.message}</span>
          )}
          {definitionId && selectableVersions.length === 0 && (versionsQuery.data?.length ?? 0) > 0 && (
            <span className="text-xs text-ink-muted">No version of this grade is valid at the selected effective time.</span>
          )}
        </div>
        <label className="flex flex-col gap-1">
          <span className={labelClass}>GPL code</span>
          <input className={inputClass} {...register(`outputs.${index}.code`)} />
          {rowErrors?.code && <span className={errorClass}>{rowErrors.code.message}</span>}
        </label>
        <label className="flex flex-col gap-1">
          <span className={labelClass}>Output weight (kg)</span>
          <input
            type="number" min={0.001} step={0.001} className={inputClass}
            {...register(`outputs.${index}.output_weight_kg`, { valueAsNumber: true })}
          />
          {rowErrors?.output_weight_kg && <span className={errorClass}>{rowErrors.output_weight_kg.message}</span>}
        </label>
        {countMode && (
          <label className="flex flex-col gap-1">
            <span className={labelClass}>Output count</span>
            <input
              type="number" min={1} step={1} className={inputClass}
              {...register(`outputs.${index}.output_whole_unit_count`, { valueAsNumber: true })}
            />
            {rowErrors?.output_whole_unit_count && (
              <span className={errorClass}>{rowErrors.output_whole_unit_count.message}</span>
            )}
          </label>
        )}
      </div>
      {removable && (
        <Button type="button" variant="secondary" className="mt-2" onClick={onRemove}>
          Remove output
        </Button>
      )}
    </li>
  );
}
