"use client";

import { useEffect, useMemo, useState } from "react";

import { Button } from "@/components/ui/Button";
import type {
  BatchOperationalContext,
  ObservationDefinitionRead,
  ObservationEventCreate,
  ObservationTargetRead,
} from "@/lib/api/client";
import { AppError, friendlyMutationErrorMessage } from "@/lib/errors/adapter";

const inputClass =
  "min-h-10 w-full rounded-md border border-wl-border bg-wl-surface-raised px-3 text-sm text-wl-text focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-wl-focus";
const labelClass = "text-xs font-medium text-wl-text-secondary";
const errorClass = "text-xs text-wl-flag-fg";

// PILOT-UX-003: a plain positional cap, not a domain judgment about which
// measurements matter more -- Observation Definitions carry no "common"/
// priority flag from configuration, so this only limits how many rows show
// before "Show more" without asserting any agronomic importance.
const ROUTINE_DEFINITION_LIMIT = 6;

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
  onDirtyChange,
  isSubmitting,
  serverError,
}: {
  batch: BatchOperationalContext;
  definitions: ObservationDefinitionRead[];
  targets: ObservationTargetRead[];
  targetsLoading: boolean;
  onSubmit: (payload: ObservationEventCreate) => void;
  onCancel: () => void;
  /** PILOT-UX-003: fires whenever "has the operator entered anything worth
   * not silently discarding" changes, so the parent page can warn before a
   * Batch switch would wipe an in-progress draft. Purely a UI convenience --
   * this component owns no persistence of its own. */
  onDirtyChange?: (dirty: boolean) => void;
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
  const [primaryTargetId, setPrimaryTargetId] = useState("");
  const [showAllDefinitions, setShowAllDefinitions] = useState(false);

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
  const isDirty = filledCount > 0 || note.trim() !== "";
  // A side effect (telling the parent something changed), not a render
  // value -- belongs in an effect, never invoked directly in the render body.
  useEffect(() => {
    onDirtyChange?.(isDirty);
  }, [isDirty, onDirtyChange]);

  // Definitions that can take a specific target at all -- these are the
  // ones a chosen "Primary target" convenience can apply to.
  const targetableDefinitions = useMemo(
    () => activeDefinitions.filter((d) => d.target_scope !== "crop_batch"),
    [activeDefinitions],
  );
  const visibleDefinitions = activeDefinitions.filter(
    (d, idx) => showAllDefinitions || idx < ROUTINE_DEFINITION_LIMIT || Boolean(rows[d.id]?.raw.trim()) || Boolean(rows[d.id]?.targetId),
  );
  const hiddenCount = activeDefinitions.length - visibleDefinitions.length;

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
    <div className="flex flex-col gap-4 rounded-xl border border-wl-border bg-wl-surface-raised p-4">
      <div className="flex items-center justify-between">
        <h2 className="font-serif text-base font-semibold text-wl-text">
          Record observation — {batch.code}
        </h2>
        <Button type="button" variant="secondary" onClick={onCancel}>
          Cancel
        </Button>
      </div>

      {activeDefinitions.length === 0 ? (
        <p className="text-sm text-wl-text-secondary">
          No active Observation Definitions are configured for this tenant yet.
        </p>
      ) : (
        <div className="flex flex-col gap-3">
          {targetableDefinitions.length > 0 && targets.length > 0 && (
            <label className="flex flex-col gap-1 rounded-lg border border-wl-border bg-wl-surface-sunken p-2.5">
              <span className={labelClass}>
                Primary target — applies to every measurement below that takes a specific target; override any row
                individually after
              </span>
              <select
                className={inputClass}
                value={primaryTargetId}
                disabled={targetsLoading}
                onChange={(e) => {
                  const value = e.target.value;
                  setPrimaryTargetId(value);
                  for (const d of targetableDefinitions) setRow(d.id, { targetId: value });
                }}
              >
                <option value="">Whole batch</option>
                {targets.map((t) => (
                  <option key={t.id} value={t.id}>
                    {targetLabel(t)}
                  </option>
                ))}
              </select>
            </label>
          )}
          {visibleDefinitions.map((definition) => {
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
              <div key={definition.id} className="grid grid-cols-1 gap-2 rounded-lg border border-wl-border p-2.5 sm:grid-cols-[1fr_auto]">
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
                  <div className="flex flex-col gap-1 sm:w-56">
                    <label className="flex flex-col gap-1">
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
                    {/* CLAUDE.md/PILOT-UX-003: scope must be explicit, never
                        just implied by an empty vs. filled dropdown. Kept as
                        a SIBLING of the <label>, never nested inside it --
                        see `PackingInputLineRow`'s identical note: folding
                        this into the select's accessible name is wrong for
                        assistive tech and breaks exact-name label queries. */}
                    <span className="text-[11px] text-wl-text-secondary">
                      Applies to: {row?.targetId ? targets.find((t) => t.id === row.targetId)?.carrier.code ?? "Selected carrier" : "Whole batch"}
                    </span>
                  </div>
                )}
              </div>
            );
          })}
          {hiddenCount > 0 && (
            <Button type="button" variant="secondary" className="self-start" onClick={() => setShowAllDefinitions(true)}>
              Show {hiddenCount} more measurement{hiddenCount === 1 ? "" : "s"}
            </Button>
          )}
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
