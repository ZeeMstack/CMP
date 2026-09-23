"use client";

import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { useMemo, useState } from "react";

import { Breadcrumbs } from "@/components/Breadcrumbs";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { LoadingSkeleton } from "@/components/LoadingSkeleton";
import { BoundedDataRegion } from "@/components/layout/BoundedDataRegion";
import { ContextStrip, ContextStripFact, ContextStripItem } from "@/components/layout/ContextStrip";
import { InspectorShell } from "@/components/layout/InspectorShell";
import { SplitWorkspace } from "@/components/layout/SplitWorkspace";
import { ObservationHistoryTable } from "@/components/observations/ObservationHistoryTable";
import { PageHeader } from "@/components/PageHeader";
import { RecordObservationForm } from "@/components/observations/RecordObservationForm";
import { Button } from "@/components/ui/Button";
import type { ObservationEventCreate } from "@/lib/api/client";
import { AppError } from "@/lib/errors/adapter";
import { formatDateTime } from "@/lib/format/datetime";
import { formatPlacementSummary } from "@/lib/format/placement";
import {
  useBatchObservationTargets,
  useFarm,
  useObservationDefinitions,
  useObservationHistory,
  useOperationalSummary,
  useRecordObservation,
} from "@/lib/query/hooks";

function asAppError(error: unknown): AppError {
  return error instanceof AppError ? error : new AppError("server_error", "Something went wrong. Please try again.");
}

/** AGRONOMY-OPS-001: the first operator UI for the Observation domain
 * (backend/definitions/permissions already existed, see the ticket's own
 * backend-verification pass) -- one reusable workspace for Nursery, Leafy,
 * and Vines batches alike, never a per-stage screen. Batch selection reuses
 * `useOperationalSummary` (already farm-wide and crop-agnostic, CMP-FE-002A)
 * rather than a new "which stages are supported" listing.
 *
 * History is necessarily Batch-scoped: the backend only exposes `GET .../
 * crop-batches/{batch_id}/observations`, no farm- or tenant-wide observation
 * feed (see docs/product/OPEN-QUESTIONS.md) -- adding one would be a second,
 * larger backend read past this ticket's "one small read endpoint" allowance,
 * not the target-selection gap that allowance is for.
 *
 * UX-OPS-001C: a compact guided workspace -- Batch selection and derived
 * Stage/Placement facts in a context strip, history (bounded) or the
 * unchanged Record form in the main area, and a Batch rail holding the
 * result banner plus the currently valid actions (Record observation,
 * Inspect Crop). Same payloads, command identity, and draft-discard
 * confirmation as before. */
export default function ObservationsPage() {
  const { farmId } = useParams<{ farmId: string }>();
  const searchParams = useSearchParams();
  const prefillBatchId = searchParams.get("batchId");
  const prefillAssignmentId = searchParams.get("assignmentId");
  // PILOT-OPS-001: a Today-on-the-Farm Work Item's "Open Observation"
  // action carries its own id through so the resulting Observation can
  // complete it -- see WorkItemRow.tsx. Never required; absent for every
  // other entry point into this page.
  const prefillWorkItemId = searchParams.get("workItemId");

  // UX-OPS-001C/R2: the URL prefill (Batch / assignment / Work Item) that
  // is actually in effect. A same-route query change re-applies it --
  // selecting the new Batch and resetting the draft, carried target, and
  // Work Item link -- so an old Batch/assignment/work item can never stay
  // active. Deferred (never forced) while the Record form holds an
  // in-flight or unresolved attempt; it applies once that resolves.
  const [applied, setApplied] = useState({
    batchId: prefillBatchId, assignmentId: prefillAssignmentId, workItemId: prefillWorkItemId,
  });
  const [selectedBatchId, setSelectedBatchId] = useState<string | null>(prefillBatchId);
  const [showRecordForm, setShowRecordForm] = useState(Boolean(prefillBatchId));
  const [recordError, setRecordError] = useState<AppError | null>(null);
  const [recordedCount, setRecordedCount] = useState<number | null>(null);
  const [recordedEffectiveTime, setRecordedEffectiveTime] = useState<string | null>(null);
  const [workItemLinkStatus, setWorkItemLinkStatus] = useState<"linked" | "failed" | null>(null);
  const [formDirty, setFormDirty] = useState(false);
  // UX-OPS-001C/R1: true while the Record form holds an in-flight or
  // unresolved attempt -- a Batch switch would unmount it and lose its
  // frozen Retry, so the selector is locked until it resolves.
  const [commandLocked, setCommandLocked] = useState(false);
  if (
    !commandLocked &&
    (applied.batchId !== prefillBatchId ||
      applied.assignmentId !== prefillAssignmentId ||
      applied.workItemId !== prefillWorkItemId)
  ) {
    setApplied({ batchId: prefillBatchId, assignmentId: prefillAssignmentId, workItemId: prefillWorkItemId });
    setSelectedBatchId(prefillBatchId);
    setShowRecordForm(Boolean(prefillBatchId));
    setRecordError(null);
    setRecordedCount(null);
    setRecordedEffectiveTime(null);
    setWorkItemLinkStatus(null);
    setFormDirty(false);
  }

  const farmQuery = useFarm(farmId);
  const batchesQuery = useOperationalSummary(farmId, "active");
  const definitionsQuery = useObservationDefinitions();
  const historyQuery = useObservationHistory(farmId, selectedBatchId);
  const targetsQuery = useBatchObservationTargets(farmId, selectedBatchId);
  const recordMutation = useRecordObservation(farmId);

  const batches = useMemo(() => batchesQuery.data ?? [], [batchesQuery.data]);
  const selectedBatch = useMemo(
    () => batches.find((b) => b.id === selectedBatchId) ?? null,
    [batches, selectedBatchId],
  );
  // Only events that carry generic Observation Definition values belong on
  // this log -- an event recorded through the separate, dedicated
  // Germination Check flow (same underlying ObservationEvent table, but
  // its own fields, see app/schemas/observation_event.py's
  // GerminationCheckIn) is out of this ticket's scope and would otherwise
  // render as a misleading blank row.
  const events = (historyQuery.data ?? []).filter((e) => e.values.length > 0);

  // PILOT-UX-003: a Batch switch always invalidates an in-progress
  // Observation draft -- measurements/targets belong to the Batch they were
  // entered against, so carrying them into a different one would be wrong,
  // not merely inconvenient. But that invalidation must never be silent: if
  // the operator has actually typed something, confirm before discarding it
  // (never for an untouched, empty form -- that would just be noise).
  function handleSelectBatch(batchId: string) {
    if (showRecordForm && formDirty) {
      const confirmed = window.confirm(
        "You have an in-progress observation for the current batch that hasn't been recorded. Switch batches and discard it?",
      );
      if (!confirmed) return;
    }
    setSelectedBatchId(batchId || null);
    setShowRecordForm(false);
    setRecordError(null);
    setRecordedCount(null);
    setRecordedEffectiveTime(null);
    setFormDirty(false);
  }

  // UX-OPS-001C/R1: a carried-forward placement is resolved against the
  // Batch's own authoritative observation targets and shown as its carrier
  // code + location -- never trusted blindly. Only a resolved placement is
  // handed on to Inspect Crop; otherwise Inspect Crop opens without one and
  // requires the operator to choose an exact placement there.
  const carriedAssignmentId = selectedBatchId === applied.batchId ? applied.assignmentId : null;
  const carriedTarget = carriedAssignmentId
    ? (targetsQuery.data ?? []).find((t) => t.id === carriedAssignmentId) ?? null
    : null;
  const carriedTargetMissing = Boolean(carriedAssignmentId) && targetsQuery.isSuccess && !carriedTarget;
  const inspectHref = selectedBatch
    ? `/farms/${farmId}/production/inspect?batchId=${selectedBatch.id}${carriedTarget ? `&assignmentId=${carriedTarget.id}` : ""}`
    : null;

  return (
    <div>
      <PageHeader
        compact
        title="Observations"
        breadcrumbs={
          <Breadcrumbs
            items={[
              { label: "Home", href: `/farms/${farmId}` },
              { label: "Production Operations" },
              { label: "Observations" },
            ]}
          />
        }
      />

      <div className="mb-4">
        <ContextStrip>
          <ContextStripItem minWidth="16rem">
            <label className="text-xs font-medium text-wl-text-secondary" htmlFor="observation-batch-select">
              Batch
            </label>
            <select
              id="observation-batch-select"
              className="min-h-11 w-full max-w-md rounded-md border border-wl-border bg-wl-surface-raised px-3 text-sm text-wl-text focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-wl-focus"
              value={selectedBatchId ?? ""}
              onChange={(e) => handleSelectBatch(e.target.value)}
              disabled={batchesQuery.isLoading || commandLocked}
            >
              <option value="">{batchesQuery.isLoading ? "Loading batches…" : "Select a batch…"}</option>
              {batches.map((b) => (
                <option key={b.id} value={b.id}>
                  {b.code} · {b.crop.common_name}
                  {b.variety ? ` / ${b.variety.name}` : ""} · {b.current_stage.name}
                </option>
              ))}
            </select>
          </ContextStripItem>
          {selectedBatch && (
            <>
              <ContextStripFact label="Stage" value={selectedBatch.current_stage.name} />
              <ContextStripFact label="Placement" value={formatPlacementSummary(selectedBatch.placement)} />
              {carriedAssignmentId && (
                <ContextStripFact
                  label="Exact placement"
                  value={
                    carriedTarget ? (
                      `${carriedTarget.carrier.code}${carriedTarget.location_label ? ` — ${carriedTarget.location_label}` : ""}`
                    ) : carriedTargetMissing ? (
                      <span className="text-wl-flag-fg">No longer an active placement of this Batch</span>
                    ) : (
                      "Resolving…"
                    )
                  }
                />
              )}
            </>
          )}
        </ContextStrip>
      </div>

      {batchesQuery.isError && <ErrorState error={batchesQuery.error} onRetry={() => batchesQuery.refetch()} />}

      {!selectedBatch ? (
        <EmptyState
          title="Select a batch to view or record observations"
          description="Observations are recorded and reviewed per crop batch, across Nursery, Leafy, and Vines Production."
        />
      ) : (
        <SplitWorkspace
          main={
            showRecordForm ? (
              <RecordObservationForm
                // Keyed by Batch AND applied prefill: a different Batch or
                // URL scope never inherits this form's draft or frozen attempt.
                key={`${selectedBatch.id}|${applied.batchId ?? ""}|${applied.assignmentId ?? ""}|${applied.workItemId ?? ""}`}
                onCommandLockedChange={setCommandLocked}
                batch={selectedBatch}
                definitions={definitionsQuery.data ?? []}
                definitionsLoading={definitionsQuery.isLoading}
                targets={targetsQuery.data ?? []}
                targetsLoading={targetsQuery.isLoading}
                initialTargetId={carriedAssignmentId}
                workItemId={selectedBatchId === applied.batchId ? applied.workItemId : null}
                isSubmitting={recordMutation.isPending}
                serverError={recordError}
                onDirtyChange={setFormDirty}
                onCancel={() => {
                  setShowRecordForm(false);
                  setRecordError(null);
                  setFormDirty(false);
                }}
                onSubmit={(payload: ObservationEventCreate) => {
                  setRecordError(null);
                  return recordMutation.mutateAsync(
                    {
                      batchId: selectedBatch.id,
                      // `work_item_id` is part of the form's frozen payload,
                      // so a Retry can never pick up a different Work Item.
                      payload,
                    },
                  ).then(
                    (result) => {
                      setShowRecordForm(false);
                      setRecordedCount(result.values.length);
                      // HOTFIX-TIME-002: the actual server-authoritative
                      // recorded time, never the pre-save browser-generated
                      // estimate the form showed while "Now" was selected.
                      setRecordedEffectiveTime(result.effective_time);
                      setWorkItemLinkStatus(result.work_item_link_status ?? null);
                      setFormDirty(false);
                    },
                    (error) => {
                      const appError = asAppError(error);
                      setRecordError(appError);
                      throw appError;
                    },
                  );
                }}
              />
            ) : (
              <>
                {historyQuery.isLoading && <LoadingSkeleton rows={4} label="Loading observation history" />}
                {historyQuery.isError && (
                  <ErrorState error={historyQuery.error} onRetry={() => historyQuery.refetch()} />
                )}
                {historyQuery.isSuccess && events.length === 0 && (
                  <EmptyState
                    title="No observations recorded yet for this batch."
                    description="Use Record observation to log the first one."
                  />
                )}
                {historyQuery.isSuccess && events.length > 0 && (
                  <BoundedDataRegion label="Observation history">
                    <ObservationHistoryTable events={events} timeZone={farmQuery.data?.timezone} />
                  </BoundedDataRegion>
                )}
              </>
            )
          }
          rail={
            <InspectorShell
              title={selectedBatch.code}
              subtitle={`${selectedBatch.crop.common_name}${selectedBatch.variety ? ` / ${selectedBatch.variety.name}` : ""}`}
            >
              {recordedCount !== null && !showRecordForm && (
                <div role="status" className="rounded-lg border border-wl-border bg-wl-grow-bg px-3 py-2 text-sm text-wl-grow-fg">
                  Recorded {recordedCount} observation{recordedCount === 1 ? "" : "s"} for {selectedBatch.code}
                  {/* HOTFIX-TIME-002: the actual server-authoritative recorded
                      time, never the pre-save browser-generated estimate. */}
                  {recordedEffectiveTime ? ` at ${formatDateTime(recordedEffectiveTime)}` : ""}.
                  {/* The Observation itself is always authoritative and
                      successful here -- a failed Work Item link is never an
                      Observation failure, and the Observation is never
                      repeated to retry it (CLAUDE.md "Transaction-backed
                      completion"). */}
                  {workItemLinkStatus === "failed" && (
                    <span className="mt-1 block text-wl-hold-fg">
                      The linked work item couldn&apos;t be marked complete automatically — reopen it from Today on the
                      Farm to reconcile.
                    </span>
                  )}
                </div>
              )}
              <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
                <div>
                  <dt className="text-xs text-wl-text-secondary">Stage</dt>
                  <dd className="text-wl-text">{selectedBatch.current_stage.name}</dd>
                </div>
                <div>
                  <dt className="text-xs text-wl-text-secondary">Recorded</dt>
                  <dd className="tabular-nums text-wl-text">{historyQuery.isSuccess ? events.length.toLocaleString() : "—"}</dd>
                </div>
              </dl>
              {!showRecordForm && (
                <Button
                  type="button"
                  variant="primary"
                  onClick={() => {
                    setShowRecordForm(true);
                    setRecordError(null);
                    setRecordedCount(null);
                    setRecordedEffectiveTime(null);
                  }}
                >
                  + Record observation
                </Button>
              )}
              {inspectHref && (
                <Link href={inspectHref} className="inline-flex min-h-9 items-center text-sm font-medium text-wl-brand hover:underline">
                  {carriedTarget ? `Inspect Crop — ${carriedTarget.carrier.code}` : "Inspect Crop (choose placement)"}
                </Link>
              )}
            </InspectorShell>
          }
        />
      )}
    </div>
  );
}
