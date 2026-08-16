"use client";

import { useParams } from "next/navigation";
import { useState } from "react";

import { Breadcrumbs } from "@/components/Breadcrumbs";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { LoadingSkeleton } from "@/components/LoadingSkeleton";
import { RecordDispositionForm } from "@/components/nursery/RecordDispositionForm";
import { SeedlingDispositionHistoryPanel } from "@/components/nursery/SeedlingDispositionHistoryPanel";
import { PageHeader } from "@/components/PageHeader";
import { StatusBadge, type StatusTone } from "@/components/StatusBadge";
import { AppError } from "@/lib/errors/adapter";
import { useRecordSeedlingDisposition, useSeedlingBiologicalTrays } from "@/lib/query/hooks";

function errorMessage(error: unknown): string {
  return error instanceof AppError ? error.message : "Something went wrong. Please try again.";
}

/** NURSERY-OPS-003B: the dedicated Seedling page -- current living quantity
 * per Tray plus biological disposition recording/correction. Deliberately
 * separate from the Germination page (which owns physical placement and
 * the Germination-outcome handoff only, not post-handoff biological
 * quantity changes). */
export default function SeedlingPage() {
  const { farmId } = useParams<{ farmId: string }>();
  const [recordingAssignmentId, setRecordingAssignmentId] = useState<string | "new" | null>(null);
  const [historyEntryId, setHistoryEntryId] = useState<string | null>(null);
  const [serverError, setServerError] = useState<string | null>(null);

  const traysQuery = useSeedlingBiologicalTrays(farmId);
  const recordMutation = useRecordSeedlingDisposition(farmId);

  function closeForm() {
    setRecordingAssignmentId(null);
    setServerError(null);
  }

  return (
    <div>
      <PageHeader
        title="Seedling"
        breadcrumbs={
          <Breadcrumbs
            items={[
              { label: "Home", href: `/farms/${farmId}` },
              { label: "Batches", href: `/farms/${farmId}/crop-batches` },
              { label: "Seedling" },
            ]}
          />
        }
        actions={
          recordingAssignmentId === null &&
          historyEntryId === null && (
            <button
              type="button"
              onClick={() => setRecordingAssignmentId("new")}
              className="min-h-11 rounded-md bg-brand-700 px-4 text-sm font-medium text-white hover:bg-brand-800"
            >
              Record biological disposition
            </button>
          )
        }
      />

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
          {traysQuery.isSuccess && traysQuery.data.length === 0 && (
            <EmptyState
              title="No Seedling Trays yet"
              description="Trays appear here once a Seedling entry has been recorded from Germination."
            />
          )}
          {traysQuery.isSuccess && traysQuery.data.length > 0 && (
            <div className="overflow-x-auto rounded-lg border border-border-subtle">
              <table className="w-full text-left text-sm">
                <thead className="border-b border-border-subtle bg-surface-subtle text-xs uppercase text-ink-muted">
                  <tr>
                    <th className="px-4 py-2 font-medium">Batch</th>
                    <th className="px-4 py-2 font-medium">Seed Tray</th>
                    <th className="px-4 py-2 font-medium">Table</th>
                    <th className="px-4 py-2 font-medium">Starting</th>
                    <th className="px-4 py-2 font-medium">Current</th>
                    <th className="px-4 py-2 font-medium">Status</th>
                    <th className="px-4 py-2 font-medium" />
                  </tr>
                </thead>
                <tbody className="divide-y divide-border-subtle">
                  {traysQuery.data.map((row) => {
                    const tone: StatusTone = row.is_depleted
                      ? "attention"
                      : row.assignment_active
                        ? "active"
                        : "closed";
                    const label = row.is_depleted ? "Depleted" : row.assignment_active ? "Active" : "Released";
                    return (
                      <tr key={row.seedling_entry_id}>
                        <td className="px-4 py-2 text-ink">{row.batch_code}</td>
                        <td className="px-4 py-2 text-ink">{row.tray_code}</td>
                        <td className="px-4 py-2 text-ink-muted">{row.seedling_table_code ?? "—"}</td>
                        <td className="px-4 py-2 text-ink">{row.starting_living_seedling_count.toLocaleString()}</td>
                        <td className="px-4 py-2 text-ink">{row.current_living_seedling_count.toLocaleString()}</td>
                        <td className="px-4 py-2">
                          <StatusBadge label={label} tone={tone} />
                        </td>
                        <td className="px-4 py-2">
                          <div className="flex gap-2">
                            {row.assignment_active && !row.is_depleted && (
                              <button
                                type="button"
                                onClick={() => setRecordingAssignmentId(row.batch_carrier_assignment_id)}
                                className="min-h-11 rounded-md border border-border-subtle px-3 text-sm font-medium text-ink hover:bg-surface-subtle"
                              >
                                Record
                              </button>
                            )}
                            {row.event_count > 0 && (
                              <button
                                type="button"
                                onClick={() => setHistoryEntryId(row.seedling_entry_id)}
                                className="min-h-11 rounded-md border border-border-subtle px-3 text-sm font-medium text-ink hover:bg-surface-subtle"
                              >
                                History
                              </button>
                            )}
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </div>
  );
}
