"use client";

import { useParams, useSearchParams } from "next/navigation";
import { useMemo, useState } from "react";

import { Breadcrumbs } from "@/components/Breadcrumbs";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { LoadingSkeleton } from "@/components/LoadingSkeleton";
import { ObservationHistoryTable } from "@/components/observations/ObservationHistoryTable";
import { PageHeader } from "@/components/PageHeader";
import { RecordObservationForm } from "@/components/observations/RecordObservationForm";
import { Button } from "@/components/ui/Button";
import type { ObservationEventCreate } from "@/lib/api/client";
import { AppError } from "@/lib/errors/adapter";
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
 * not the target-selection gap that allowance is for. */
export default function ObservationsPage() {
  const { farmId } = useParams<{ farmId: string }>();
  const searchParams = useSearchParams();
  const prefillBatchId = searchParams.get("batchId");

  const [selectedBatchId, setSelectedBatchId] = useState<string | null>(prefillBatchId);
  const [showRecordForm, setShowRecordForm] = useState(Boolean(prefillBatchId));
  const [recordError, setRecordError] = useState<AppError | null>(null);
  const [recordedCount, setRecordedCount] = useState<number | null>(null);

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

  function handleSelectBatch(batchId: string) {
    setSelectedBatchId(batchId || null);
    setShowRecordForm(false);
    setRecordError(null);
    setRecordedCount(null);
  }

  return (
    <div>
      <PageHeader
        title="Observations"
        description="Record and review crop observations — plant height, pest signs, EC/pH, and any other configured metric."
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

      <div className="mb-4 flex flex-col gap-1.5">
        <label className="text-xs font-medium text-ink-muted" htmlFor="observation-batch-select">
          Batch
        </label>
        <select
          id="observation-batch-select"
          className="min-h-11 w-full max-w-md rounded-md border border-border-subtle bg-surface px-3 text-sm text-ink focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-600"
          value={selectedBatchId ?? ""}
          onChange={(e) => handleSelectBatch(e.target.value)}
          disabled={batchesQuery.isLoading}
        >
          <option value="">{batchesQuery.isLoading ? "Loading batches…" : "Select a batch…"}</option>
          {batches.map((b) => (
            <option key={b.id} value={b.id}>
              {b.code} · {b.crop.common_name}
              {b.variety ? ` / ${b.variety.name}` : ""} · {b.current_stage.name}
            </option>
          ))}
        </select>
      </div>

      {batchesQuery.isError && <ErrorState error={batchesQuery.error} onRetry={() => batchesQuery.refetch()} />}

      {!selectedBatch ? (
        <EmptyState
          title="Select a batch to view or record observations"
          description="Observations are recorded and reviewed per crop batch, across Nursery, Leafy, and Vines Production."
        />
      ) : (
        <div className="flex flex-col gap-4">
          <div className="flex flex-col gap-2 rounded-xl border border-border-subtle bg-surface p-3 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex flex-col gap-0.5">
              <span className="text-sm font-medium text-ink">
                {selectedBatch.code} · {selectedBatch.crop.common_name}
                {selectedBatch.variety ? ` / ${selectedBatch.variety.name}` : ""}
              </span>
              <span className="text-xs text-ink-muted">
                {selectedBatch.current_stage.name} · {formatPlacementSummary(selectedBatch.placement)}
              </span>
            </div>
            {!showRecordForm && (
              <Button
                type="button"
                variant="primary"
                onClick={() => {
                  setShowRecordForm(true);
                  setRecordError(null);
                  setRecordedCount(null);
                }}
              >
                + Record observation
              </Button>
            )}
          </div>

          {recordedCount !== null && !showRecordForm && (
            <div className="rounded-lg border border-green-200 bg-green-50 px-3 py-2 text-sm text-green-800">
              Recorded {recordedCount} observation{recordedCount === 1 ? "" : "s"} for {selectedBatch.code}.
            </div>
          )}

          {showRecordForm ? (
            <RecordObservationForm
              batch={selectedBatch}
              definitions={definitionsQuery.data ?? []}
              targets={targetsQuery.data ?? []}
              targetsLoading={targetsQuery.isLoading}
              isSubmitting={recordMutation.isPending}
              serverError={recordError}
              onCancel={() => {
                setShowRecordForm(false);
                setRecordError(null);
              }}
              onSubmit={(payload: ObservationEventCreate) => {
                setRecordError(null);
                recordMutation.mutate(
                  { batchId: selectedBatch.id, payload },
                  {
                    onSuccess: (result) => {
                      setShowRecordForm(false);
                      setRecordedCount(result.values.length);
                    },
                    onError: (error) => setRecordError(asAppError(error)),
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
                <ObservationHistoryTable events={events} timeZone={farmQuery.data?.timezone} />
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}
