import Link from "next/link";

import { InspectorEmptyState, InspectorShell } from "@/components/layout/InspectorShell";
import { StatusBadge, type StatusTone } from "@/components/StatusBadge";
import { Button } from "@/components/ui/Button";
import type { GerminationTrayRead } from "@/lib/api/client";
import type { GerminationNextAction, GerminationObservationStatus, GerminationWorklistRow } from "@/lib/query/hooks";

const PLACEMENT_LABEL: Record<GerminationTrayRead["state"], string> = {
  awaiting_placement: "Awaiting placement",
  elsewhere: "Elsewhere",
  in_germination: "In Germination",
};
const PLACEMENT_TONE: Record<GerminationTrayRead["state"], StatusTone> = {
  awaiting_placement: "attention",
  elsewhere: "neutral",
  in_germination: "active",
};
const OBSERVATION_LABEL: Record<GerminationObservationStatus, string> = {
  not_observed: "Not observed",
  interim: "Interim",
  final: "Final",
};
const OBSERVATION_TONE: Record<GerminationObservationStatus, StatusTone> = {
  not_observed: "neutral",
  interim: "attention",
  final: "active",
};

export function nextActionLabel(action: GerminationNextAction): string | null {
  switch (action.kind) {
    case "place":
      return "Move to Germination";
    case "record_outcome":
      return action.isUpdate ? "Update outcome" : "Record outcome";
    case "move_to_seedling":
      return "Move to Seedling";
    case "none":
      return null;
  }
}

function formatDateTime(iso: string | null): string | null {
  if (!iso) return null;
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

/** UX-OPS-001B: the Germination selected-item inspector -- shows exactly
 * the facts the existing row-expansion accordion showed, plus the ONE
 * currently-valid next action (reusing `GerminationWorklistRow.nextAction`,
 * the worklist's own established valid-action logic, never re-derived
 * here). Clicking the action button hands off to the existing, unchanged
 * command form (rendered by the page, full-width, exactly as before) --
 * this component never itself submits a command. */
export function GerminationInspector({
  row,
  farmId,
  onOpenAction,
  onClose,
}: {
  row: GerminationWorklistRow | null;
  farmId: string;
  onOpenAction: (row: GerminationWorklistRow) => void;
  onClose: () => void;
}) {
  if (!row) return <InspectorEmptyState />;

  const actionLabel = nextActionLabel(row.nextAction);
  const latestObservedAt = formatDateTime(row.latestObservedAt);

  return (
    <InspectorShell title={row.trayCode} subtitle={`Batch ${row.batchCode} · ${row.cropName} / ${row.varietyName}`} onClose={onClose}>
      <div className="flex flex-col gap-1.5">
        <StatusBadge label={PLACEMENT_LABEL[row.placementState]} tone={PLACEMENT_TONE[row.placementState]} />
        <p className="text-xs text-wl-text-secondary">{row.placementLabel ?? "—"}</p>
      </div>
      <div className="flex flex-col gap-1.5">
        <StatusBadge label={OBSERVATION_LABEL[row.observationStatus]} tone={OBSERVATION_TONE[row.observationStatus]} />
        <p className="text-xs text-wl-text-secondary">
          {row.normalCount === null && row.abnormalCount === null
            ? "—"
            : `${row.normalCount ?? 0} normal / ${row.abnormalCount ?? 0} abnormal`}
        </p>
      </div>
      <dl className="grid grid-cols-2 gap-x-3 gap-y-1.5 text-xs text-wl-text-secondary">
        <div>
          <dt>Seed Lot</dt>
          <dd className="font-medium text-wl-text">{row.seedLotCode}</dd>
        </div>
        <div>
          <dt>Seeds sown</dt>
          <dd className="font-medium text-wl-text">{row.seedsSown.toLocaleString()}</dd>
        </div>
        <div>
          <dt>Sown Sites</dt>
          <dd className="font-medium text-wl-text">{row.sownSiteCount ?? "Not recorded"}</dd>
        </div>
        <div>
          <dt>Prior observations</dt>
          <dd className="font-medium text-wl-text">{row.historicalSnapshotCount}</dd>
        </div>
        {latestObservedAt && (
          <div className="col-span-2">
            <dt>Latest observed at</dt>
            <dd className="font-medium text-wl-text">{latestObservedAt}</dd>
          </div>
        )}
      </dl>
      <div className="flex flex-wrap items-center gap-2 border-t border-wl-border pt-3">
        {actionLabel ? (
          <Button type="button" variant="primary" onClick={() => onOpenAction(row)}>
            {actionLabel}
          </Button>
        ) : (
          <span className="text-xs text-wl-text-secondary">No action currently valid for this Seed Tray.</span>
        )}
        {row.placementState === "in_germination" && (
          <Link
            href={`/farms/${farmId}/labels/batch_carrier_assignment/${row.assignmentId}`}
            className="text-xs font-medium text-wl-text-secondary underline hover:text-wl-text"
          >
            Reprint label
          </Link>
        )}
      </div>
    </InspectorShell>
  );
}
