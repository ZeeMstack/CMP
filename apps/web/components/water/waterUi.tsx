"use client";

import type { ReactNode } from "react";

import { Breadcrumbs } from "@/components/Breadcrumbs";
import { PageHeader } from "@/components/PageHeader";
import { WaterSubNav } from "@/components/water/WaterSubNav";
import { UNCERTAIN_OUTCOME_COPY } from "@/lib/commands/frozenSubmission";
import { friendlyMutationErrorMessage, type AppError } from "@/lib/errors/adapter";

const UUID_ONLY = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** UX-OPS-001D: small Water-workspace-only helpers shared by the five
 * operational routes (never by Water Setup). Purely presentational/format
 * helpers -- no domain rule lives here. */

export const inputClass =
  "min-h-11 w-full rounded-md border border-wl-border bg-wl-surface-raised px-2.5 text-sm text-wl-text focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-wl-focus disabled:cursor-not-allowed disabled:opacity-70";
export const labelClass = "flex min-w-0 flex-col gap-1 text-sm";
export const labelTextClass = "text-xs font-medium text-wl-text-secondary";
export const blockerListClass =
  "flex flex-col gap-1 rounded-lg bg-wl-flag-bg px-3 py-2 text-xs font-medium text-wl-flag-fg";
export const cardClass = "rounded-xl border border-wl-border bg-wl-surface-raised p-4";
export const stepLabelClass = "mb-2 text-xs font-semibold uppercase tracking-wide text-wl-brand";
export const linkButtonClass =
  "inline-flex min-h-11 items-center justify-center rounded-lg border border-wl-border-strong bg-wl-surface-raised px-3 text-sm font-medium text-wl-text hover:bg-wl-surface-hover focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-wl-focus";

/** PILOT-WATER-001A canonical metric set and units
 * (app/models/water_measurement.py) -- the unit is read-only and canonical;
 * this fixed order is also the Measurement send order. */
export const WATER_METRICS = [
  { metric: "PH", label: "pH", unit: "pH", supportsFlag: "supports_ph" as const },
  { metric: "EC", label: "EC", unit: "mS/cm", supportsFlag: "supports_ec" as const },
  { metric: "SOLUTION_TEMPERATURE", label: "Solution temperature", unit: "°C", supportsFlag: "supports_solution_temperature" as const },
  { metric: "DISSOLVED_OXYGEN", label: "Dissolved oxygen", unit: "mg/L", supportsFlag: "supports_dissolved_oxygen" as const },
];

export function metricLabel(metric: string): string {
  return WATER_METRICS.find((m) => m.metric === metric)?.label ?? metric;
}

/** `CODE — Name` for a coded master-data row, or `null` when the row is not
 * (yet) resolvable -- callers say "unavailable" explicitly, never fall back
 * to a shortened UUID as an operator label. */
export function entityLabel(entity: { code: string; name: string } | null | undefined): string | null {
  return entity ? `${entity.code} — ${entity.name}` : null;
}

export function Unavailable({ what }: { what: string }) {
  return <span className="text-wl-text-tertiary">{what} label unavailable</span>;
}

/** A browser `datetime-local` value -> a timezone-aware ISO instant, or
 * `null` when blank/unparseable. Only ever used for an operator's explicit
 * custom time -- "Now" is always sent as `null` (server time). */
export function localInputToIso(local: string): string | null {
  if (!local) return null;
  const date = new Date(local);
  return Number.isNaN(date.getTime()) ? null : date.toISOString();
}

/** The operator's current local time as a `datetime-local` value -- used
 * only to PROPOSE a visible, editable End Delivery time once. */
export function nowAsLocalInput(now: Date = new Date()): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}T${pad(now.getHours())}:${pad(now.getMinutes())}`;
}

export type TimingMode = "now" | "custom";

/** "Now (server time)" vs an explicit custom time. Now sends `null`: the
 * server assigns its own authoritative time; the browser clock is never
 * submitted as "now". */
export function TimingField({
  legend,
  mode,
  custom,
  onModeChange,
  onCustomChange,
  nowLabel = "Now (server time)",
}: {
  legend: string;
  mode: TimingMode;
  custom: string;
  onModeChange: (mode: TimingMode) => void;
  onCustomChange: (value: string) => void;
  nowLabel?: string;
}) {
  const name = `timing-${legend.replace(/\W+/g, "-").toLowerCase()}`;
  return (
    <fieldset className="flex min-w-0 flex-col gap-1.5">
      <legend className={labelTextClass}>{legend}</legend>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-wl-text">
        <label className="flex min-h-11 items-center gap-2">
          <input type="radio" name={name} checked={mode === "now"} onChange={() => onModeChange("now")} />
          {nowLabel}
        </label>
        <label className="flex min-h-11 items-center gap-2">
          <input type="radio" name={name} checked={mode === "custom"} onChange={() => onModeChange("custom")} />
          Custom time
        </label>
      </div>
      {mode === "custom" && (
        <input
          type="datetime-local"
          aria-label={`${legend} (custom)`}
          className={inputClass}
          value={custom}
          onChange={(e) => onCustomChange(e.target.value)}
        />
      )}
    </fieldset>
  );
}

/** Compact header + breadcrumb + the six-view Water sub-nav (locked while
 * this page owns an in-flight/unresolved command). */
export function WaterWorkspaceHeader({
  farmId,
  title,
  description,
  locked = false,
  actions,
}: {
  farmId: string;
  title: string;
  description?: ReactNode;
  locked?: boolean;
  actions?: ReactNode;
}) {
  return (
    <>
      <PageHeader
        compact
        title={title}
        description={description}
        actions={actions}
        breadcrumbs={
          <Breadcrumbs
            items={
              title === "Water & Nutrients"
                ? [{ label: "Home", href: `/farms/${farmId}` }, { label: "Water & Nutrients" }]
                : [
                    { label: "Home", href: `/farms/${farmId}` },
                    { label: "Water & Nutrients", href: `/farms/${farmId}/water` },
                    { label: title },
                  ]
            }
          />
        }
      />
      <WaterSubNav farmId={farmId} locked={locked} />
    </>
  );
}

/** The operator-facing line for a command's current error: the server's
 * message for a definitive rejection, plus the shared uncertain-outcome
 * copy while the attempt is unresolved. */
export function commandErrorLine(error: AppError | null, uncertain: boolean): string | null {
  if (!error) return null;
  if (uncertain) return `${friendlyMutationErrorMessage(error)} ${UNCERTAIN_OUTCOME_COPY}`;
  const definitive = error.kind === "invalid_request" || error.kind === "conflict" || error.kind === "not_found";
  const message = error.message.trim();
  if (definitive && message && !UUID_ONLY.test(message)) {
    return `Not recorded — ${message}. Edit and submit again; that will be a new command.`;
  }
  return friendlyMutationErrorMessage(error);
}

export function BlockerList({ lines }: { lines: (string | null | undefined | false)[] }) {
  const shown = lines.filter((l): l is string => Boolean(l));
  if (shown.length === 0) return null;
  return (
    <ul role="alert" className={blockerListClass}>
      {shown.map((line) => (
        <li key={line}>{line}</li>
      ))}
    </ul>
  );
}

/** One read-only fact row inside a Review/Receipt/inspector. */
export function Fact({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-0.5">
      <dt className="text-xs font-medium text-wl-text-secondary">{label}</dt>
      <dd className="text-sm text-wl-text">{children}</dd>
    </div>
  );
}

export function FactList({ children }: { children: ReactNode }) {
  return <dl className="grid grid-cols-1 gap-x-4 gap-y-2 sm:grid-cols-2">{children}</dl>;
}
