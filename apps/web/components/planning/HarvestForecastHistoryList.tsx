"use client";

import { useState } from "react";

import { ErrorState } from "@/components/ErrorState";
import { LoadingSkeleton } from "@/components/LoadingSkeleton";
import { StatusBadge } from "@/components/StatusBadge";
import { formatPlanDate } from "@/lib/format/planDate";
import { formatQuantity } from "@/lib/format/planQuantity";
import { useBatchHarvestForecastHistory } from "@/lib/query/hooks";

const BASIS_LABEL: Record<string, string> = {
  grower_estimate: "Grower estimate",
  planning_assumption: "Planning assumption",
  protocol_guidance: "Protocol guidance",
};

/** PILOT-PLAN-001B section 8: forecast history is secondary/collapsible,
 * never the main worksheet -- shown oldest-first as recorded, but rendered
 * newest-first (current revision at top) for a manager scanning "what
 * changed and when". Every past revision remains permanently visible --
 * revising a forecast never hides or rewrites the ones before it. */
export function HarvestForecastHistoryList({ farmId, batchId }: { farmId: string; batchId: string }) {
  const [open, setOpen] = useState(false);
  const historyQuery = useBatchHarvestForecastHistory(farmId, open ? batchId : undefined);

  return (
    <div>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="text-sm font-medium text-wl-brand hover:underline"
        aria-expanded={open}
      >
        {open ? "Hide forecast history" : "Show forecast history"}
      </button>

      {open && (
        <div className="mt-2">
          {historyQuery.isLoading && <LoadingSkeleton rows={2} label="Loading forecast history" />}
          {historyQuery.error && <ErrorState error={historyQuery.error} onRetry={() => historyQuery.refetch()} />}
          {historyQuery.data && historyQuery.data.length > 0 && (
            <ul className="divide-y divide-wl-border rounded-md border border-wl-border">
              {[...historyQuery.data].reverse().map((revision) => (
                <li key={revision.id} className="flex flex-col gap-1 p-2.5 text-sm">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="font-medium text-wl-text">
                      Rev {revision.revision_number} · {formatPlanDate(revision.window_start_date)} –{" "}
                      {formatPlanDate(revision.window_end_date)}
                    </span>
                    <StatusBadge label={revision.is_current ? "Current" : "Superseded"} tone={revision.is_current ? "active" : "neutral"} />
                  </div>
                  <p className="text-wl-text-secondary">
                    Low {formatQuantity(revision.low_quantity, revision.uom.code)} · Expected{" "}
                    {formatQuantity(revision.expected_quantity, revision.uom.code)} · High{" "}
                    {formatQuantity(revision.high_quantity, revision.uom.code)}
                  </p>
                  <p className="text-xs text-wl-text-tertiary">
                    {BASIS_LABEL[revision.basis] ?? revision.basis} · Recorded{" "}
                    {new Date(revision.recorded_time).toLocaleString()}
                    {revision.revision_reason ? ` · ${revision.revision_reason}` : ""}
                  </p>
                  {revision.notes && <p className="text-xs text-wl-text-secondary">{revision.notes}</p>}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
