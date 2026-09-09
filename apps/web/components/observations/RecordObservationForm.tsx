"use client";

import { useMemo, useState } from "react";

import { Button } from "@/components/ui/Button";
import type {
  BatchOperationalContext,
  ObservationDefinitionRead,
  ObservationEventCreate,
  ObservationTargetRead,
} from "@/lib/api/client";
import { AppError, friendlyMutationErrorMessage } from "@/lib/errors/adapter";

const inputClass =
  "min-h-10 w-full rounded-md border border-border-subtle bg-surface px-3 text-sm text-ink focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-600";
const labelClass = "text-xs font-medium text-ink-muted";
const errorClass = "text-xs text-red-700";

function nowDateAndTime() {
  const now = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  return {
    date: `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`,
    time: `${pad(now.getHours())}:${pad(now.getMinutes())}`,
  };
}

function targetLabel(target: ObservationTargetRead): string {
  return target.location_label ? `${target.carrier.code} — ${target.location_label}` : target.carrier.code;
}

interface RowState {
  raw: string;
  targetId: string;
}

/** AGRONOMY-OPS-001: one compact "configure -> record" form covering every
 * active Observation Definition at once (bulk entry in a single command --
 * `ObservationEventCreate.values` already supports many definitions/targets
 * per event, see `app/schemas/observation_event.py`). No stage-specific
 * branching: `definitions`/`targets` are whatever the caller's selected
 * Batch actually has, so this same component serves Nursery, Leafy, and
 * Vines Production alike (CLAUDE.md rule 1). Only rows an operator actually
 * fills in are included in the submitted event -- an untouched definition
 * is simply omitted, never sent as a zero/false/blank value. */
export function RecordObservationForm({
  batch,
  definitions,
  targets,
  targetsLoading,
  onSubmit,
  onCancel,
  isSubmitting,
  serverError,
}: {
  batch: BatchOperationalContext;
  definitions: ObservationDefinitionRead[];
  targets: ObservationTargetRead[];
  targetsLoading: boolean;
  onSubmit: (payload: ObservationEventCreate) => void;
  onCancel: () => void;
  isSubmitting: boolean;
  serverError?: AppError | null;
}) {
  const initial = nowDateAndTime();
  const [effectiveDate, setEffectiveDate] = useState(initial.date);
  const [effectiveTime, setEffectiveTime] = useState(initial.time);
  const [note, setNote] = useState("");
  const [rows, setRows] = useState<Record<string, RowState>>({});
  const [clientCommandId] = useState(() => crypto.randomUUID());
  const [rowError, setRowError] = useState<string | null>(null);

  const activeDefinitions = useMemo(
    () => definitions.filter((d) => d.status === "active"),
    [definitions],
  );

  function setRow(definitionId: string, patch: Partial<RowState>) {
    setRows((prev) => ({
      ...prev,
      [definitionId]: { raw: prev[definitionId]?.raw ?? "", targetId: prev[definitionId]?.targetId ?? "", ...patch },
    }));
  }

  const filledCount = Object.values(rows).filter((r) => r.raw.trim() !== "").length;

  function buildValues(): ObservationEventCreate["values"] | null {
    const values: NonNullable<ObservationEventCreate["values"]> = [];
    for (const definition of activeDefinitions) {
      const row = rows[definition.id];
      const raw = row?.raw.trim();
      if (!raw) continue;

      if (definition.target_scope === "carrier_assignment" && !row?.targetId) {
        setRowError(`${definition.name} requires a target — select one of the batch's active carriers.`);
        return null;
      }

      const value: NonNullable<ObservationEventCreate["values"]>[number] = {
        observation_definition_id: definition.id,
        batch_carrier_assignment_id: row?.targetId || null,
      };
      if (definition.value_type === "integer") {
        const n = Number(raw);
        if (!Number.isInteger(n)) {
          setRowError(`${definition.name} requires a whole number.`);
          return null;
        }
        value.value_integer = n;
      } else if (definition.value_type === "decimal" || definition.value_type === "percentage") {
        if (Number.isNaN(Number(raw))) {
          setRowError(`${definition.name} requires a number.`);
          return null;
        }
        value.value_decimal = raw;
      } else if (definition.value_type === "boolean") {
        value.value_boolean = raw === "true";
      } else {
        value.value_text = raw;
      }
      values.push(value);
    }
    if (values.length === 0) {
      setRowError("Enter at least one observation value.");
      return null;
    }
    setRowError(null);
    return values;
  }

  function handleSubmit() {
    const values = buildValues();
    if (!values) return;
    const effective_time = new Date(`${effectiveDate}T${effectiveTime}`).toISOString();
    onSubmit({
      client_command_id: clientCommandId,
      effective_time,
      note: note.trim() || null,
      values,
    });
  }

  return (
    <div className="flex flex-col gap-4 rounded-xl border border-border-subtle bg-surface p-4">
      <div className="flex items-center justify-between">
        <h2 className="font-serif text-base font-semibold text-ink">
          Record observation — {batch.code}
        </h2>
        <Button type="button" variant="secondary" onClick={onCancel}>
          Cancel
        </Button>
      </div>

      {activeDefinitions.length === 0 ? (
        <p className="text-sm text-ink-muted">
          No active Observation Definitions are configured for this tenant yet.
        </p>
      ) : (
        <div className="flex flex-col gap-3">
          {activeDefinitions.map((definition) => {
            const row = rows[definition.id];
            const needsTarget = definition.target_scope !== "crop_batch";
            const bounds =
              definition.min_value !== null && definition.max_value !== null
                ? `${definition.min_value}–${definition.max_value}`
                : definition.min_value !== null
                  ? `≥ ${definition.min_value}`
                  : definition.max_value !== null
                    ? `≤ ${definition.max_value}`
                    : null;
            const fieldLabel = `${definition.name}${definition.unit ? ` (${definition.unit})` : ""}${bounds ? ` · ${bounds}` : ""}`;
            return (
              <div key={definition.id} className="grid grid-cols-1 gap-2 rounded-lg border border-border-subtle p-2.5 sm:grid-cols-[1fr_auto]">
                <label className="flex flex-col gap-1">
                  <span className={labelClass}>{fieldLabel}</span>
                  {definition.value_type === "boolean" ? (
                    <select
                      className={inputClass}
                      value={row?.raw ?? ""}
                      onChange={(e) => setRow(definition.id, { raw: e.target.value })}
                    >
                      <option value="">Not observed</option>
                      <option value="true">Yes</option>
                      <option value="false">No</option>
                    </select>
                  ) : definition.value_type === "text" ? (
                    <input
                      type="text"
                      className={inputClass}
                      value={row?.raw ?? ""}
                      onChange={(e) => setRow(definition.id, { raw: e.target.value })}
                    />
                  ) : (
                    <input
                      type="number"
                      step={definition.value_type === "integer" ? 1 : "any"}
                      className={inputClass}
                      value={row?.raw ?? ""}
                      onChange={(e) => setRow(definition.id, { raw: e.target.value })}
                    />
                  )}
                </label>
                {needsTarget && (
                  <label className="flex flex-col gap-1 sm:w-56">
                    <span className={labelClass}>
                      {definition.name} target
                      {definition.target_scope === "carrier_assignment" ? " (required)" : " (optional)"}
                    </span>
                    <select
                      className={inputClass}
                      value={row?.targetId ?? ""}
                      onChange={(e) => setRow(definition.id, { targetId: e.target.value })}
                      disabled={targetsLoading}
                    >
                      <option value="">
                        {definition.target_scope === "either" ? "Whole batch" : "Select a carrier…"}
                      </option>
                      {targets.map((t) => (
                        <option key={t.id} value={t.id}>
                          {targetLabel(t)}
                        </option>
                      ))}
                    </select>
                  </label>
                )}
              </div>
            );
          })}
        </div>
      )}

      <div className="flex flex-col gap-1">
        <span className={labelClass}>Notes (optional)</span>
        <textarea
          className={`${inputClass} min-h-16`}
          rows={2}
          value={note}
          onChange={(e) => setNote(e.target.value)}
        />
      </div>

      <fieldset className="grid grid-cols-2 gap-3">
        <div className="flex flex-col gap-1">
          <span className={labelClass}>Date</span>
          <input
            type="date"
            className={inputClass}
            value={effectiveDate}
            onChange={(e) => setEffectiveDate(e.target.value)}
          />
        </div>
        <div className="flex flex-col gap-1">
          <span className={labelClass}>Time</span>
          <input
            type="time"
            className={inputClass}
            value={effectiveTime}
            onChange={(e) => setEffectiveTime(e.target.value)}
          />
        </div>
      </fieldset>

      {rowError && (
        <p role="alert" className={errorClass}>
          {rowError}
        </p>
      )}
      {serverError && (
        <p role="alert" className={errorClass}>
          {friendlyMutationErrorMessage(serverError)}
        </p>
      )}

      <div>
        <Button type="button" variant="primary" disabled={isSubmitting} onClick={handleSubmit}>
          {isSubmitting
            ? "Recording…"
            : filledCount > 0
              ? `Record ${filledCount} observation${filledCount === 1 ? "" : "s"}`
              : "Record observation"}
        </Button>
      </div>
    </div>
  );
}
