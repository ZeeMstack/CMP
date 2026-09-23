"use client";

import { useParams } from "next/navigation";
import { useState } from "react";

import { Breadcrumbs } from "@/components/Breadcrumbs";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { BoundedDataRegion } from "@/components/layout/BoundedDataRegion";
import { QueueList, QueueRow } from "@/components/layout/QueueRow";
import { SplitWorkspace } from "@/components/layout/SplitWorkspace";
import { LoadingSkeleton } from "@/components/LoadingSkeleton";
import { NurseryJourney } from "@/components/nursery/NurseryJourney";
import { RecordDispositionForm } from "@/components/nursery/RecordDispositionForm";
import { SeedlingDispositionHistoryPanel } from "@/components/nursery/SeedlingDispositionHistoryPanel";
import { SeedlingInspector } from "@/components/nursery/SeedlingInspector";
import { PageHeader } from "@/components/PageHeader";
import { StatusBadge, type StatusTone } from "@/components/StatusBadge";
import { Button } from "@/components/ui/Button";
import { AppError } from "@/lib/errors/adapter";
import { useRecordSeedlingDisposition, useSeedlingBiologicalTrays } from "@/lib/query/hooks";

function errorMessage(error: unknown): string {
  return error instanceof AppError ? error.message : "Something went wrong. Please try again.";
}

/** NURSERY-OPS-003B: the dedicated Seedling page -- current living quantity
 * per Tray plus biological disposition recording/correction. Deliberately
 * separate from the Germination page (which owns physical placement and
 * the Germination-outcome handoff only, not post-handoff biological
 * quantity changes).
 *
 * UX-OPS-001B: one queue plus a selected-item inspector/action workspace
 * (ticket §6.2), replacing the prior full-width table -- the queue/
 * inspector split and the Record/History command forms are otherwise
 * functionally unchanged. */
export default function SeedlingPage() {
  const { farmId } = useParams<{ farmId: string }>();
  const [recordingAssignmentId, setRecordingAssignmentId] = useState<string | "new" | null>(null);
  const [historyEntryId, setHistoryEntryId] = useState<string | null>(null);
  const [serverError, setServerError] = useState<string | null>(null);
  const [selectedAssignmentId, setSelectedAssignmentId] = useState<string | null>(null);

  const traysQuery = useSeedlingBiologicalTrays(farmId);
  const recordMutation = useRecordSeedlingDisposition(farmId);

  const rows = traysQuery.data ?? [];
  const selectedRow = rows.find((r) => r.batch_carrier_assignment_id === selectedAssignmentId) ?? null;

  function closeForm() {
    setRecordingAssignmentId(null);
    setServerError(null);
  }

  return (
    <div>
      <PageHeader
        title="Seedling"
        compact
        breadcrumbs={
          <Breadcrumbs
            items={[
              { label: "Home", href: `/farms/${farmId}` },
              { label: "Nursery Operations" },
              { label: "Seedling" },
            ]}
          />
        }
        actions={
          recordingAssignmentId === null &&
          historyEntryId === null && (
            // UX-OPS-001B R1: secondary, never primary -- the selected
            // row's own "Record disposition" action (SeedlingInspector) is
            // the sole primary action whenever a row is selected. This
            // manual entry point (no row preselected) stays available but
            // subordinate, so the two never compete as co-equal blue
            // buttons on screen at once.
            <Button type="button" variant="secondary" onClick={() => setRecordingAssignmentId("new")}>
              Record biological disposition
            </Button>
          )
        }
      />
      <NurseryJourney farmId={farmId} current="seedling" />

      {recordingAssignmentId !== null && (
        <RecordDispositionForm
          farmId={farmId}
          preselectedAssignmentId={recordingAssignmentId === "new" ? undefined : recordingAssignmentId}
          isSubmitting={recordMutation.isPending}
          serverError={serverError}
          onCancel={closeForm}
          onSubmit={(payload) => {
            setServerError(null);
            recordMutation.mutate(payload, {
              onSuccess: closeForm,
              onError: (error) => setServerError(errorMessage(error)),
            });
          }}
        />
      )}

      {recordingAssignmentId === null && historyEntryId !== null && (
        <SeedlingDispositionHistoryPanel
          farmId={farmId}
          seedlingEntryId={historyEntryId}
          onClose={() => setHistoryEntryId(null)}
        />
      )}

      {recordingAssignmentId === null && historyEntryId === null && (
        <>
          {traysQuery.isLoading && <LoadingSkeleton />}
          {traysQuery.isError && <ErrorState error={traysQuery.error} onRetry={() => traysQuery.refetch()} />}
          {traysQuery.isSuccess && rows.length === 0 && (
            <EmptyState
              title="No Seedling Trays yet"
              description="Trays appear here once a Seedling entry has been recorded from Germination."
            />
          )}
          {traysQuery.isSuccess && rows.length > 0 && (
            <SplitWorkspace
              main={
                <BoundedDataRegion label="Seedling queue">
                  <QueueList label="Seedling queue">
                    {rows.map((row) => {
                      const tone: StatusTone = row.is_depleted ? "attention" : row.assignment_active ? "active" : "closed";
                      const label = row.is_depleted ? "Depleted" : row.assignment_active ? "Active" : "Released";
                      return (
                        <QueueRow
                          key={row.seedling_entry_id}
                          isSelected={row.batch_carrier_assignment_id === selectedAssignmentId}
                          onSelect={() => setSelectedAssignmentId(row.batch_carrier_assignment_id)}
                          title={row.tray_code}
                          context={`Batch ${row.batch_code}${row.seedling_table_code ? ` · ${row.seedling_table_code}` : ""}`}
                          status={<StatusBadge label={label} tone={tone} />}
                          meta={`${row.current_living_seedling_count.toLocaleString()} living`}
                        />
                      );
                    })}
                  </QueueList>
                </BoundedDataRegion>
              }
              rail={
                <SeedlingInspector
                  row={selectedRow}
                  farmId={farmId}
                  onRecord={(assignmentId) => setRecordingAssignmentId(assignmentId)}
                  onHistory={(seedlingEntryId) => setHistoryEntryId(seedlingEntryId)}
                  onClose={() => setSelectedAssignmentId(null)}
                />
              }
            />
          )}
        </>
      )}
    </div>
  );
}
