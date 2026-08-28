"use client";

import { useParams } from "next/navigation";
import { useState } from "react";

import { Breadcrumbs } from "@/components/Breadcrumbs";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { LoadingSkeleton } from "@/components/LoadingSkeleton";
import { PageHeader } from "@/components/PageHeader";
import { OpenRecallCaseForm } from "@/components/processing/OpenRecallCaseForm";
import { RecallCaseListItem } from "@/components/processing/RecallCaseListItem";
import { Button } from "@/components/ui/Button";
import { AppError } from "@/lib/errors/adapter";
import { useOpenRecallCase, useRecallCases } from "@/lib/query/hooks";

function asAppError(error: unknown): AppError {
  return error instanceof AppError ? error : new AppError("server_error", "Something went wrong. Please try again.");
}

/** PILOT-READY-001: the Recall Cases workspace -- list of every Recall
 * Case in this Farm plus an "Open Recall Case" form. Closes a confirmed
 * pilot blocker: the backend has always supported opening/closing a
 * Recall Case, but no frontend page existed for either -- only a
 * read-only "under an open recall" badge on other Processing screens. */
export default function RecallCasesPage() {
  const { farmId } = useParams<{ farmId: string }>();
  const [showForm, setShowForm] = useState(false);
  const [openError, setOpenError] = useState<AppError | null>(null);

  const { data, isLoading, error, refetch } = useRecallCases(farmId);
  const openMutation = useOpenRecallCase(farmId);

  const sorted = [...(data ?? [])].sort((a, b) => b.effective_time.localeCompare(a.effective_time));

  return (
    <div>
      <PageHeader
        title="Recall Cases"
        breadcrumbs={
          <Breadcrumbs
            items={[
              { label: "Home", href: `/farms/${farmId}` },
              { label: "Processing", href: `/farms/${farmId}/processing` },
              { label: "Recall Cases" },
            ]}
          />
        }
        actions={
          !showForm && (
            <Button type="button" variant="primary" onClick={() => setShowForm(true)}>
              Open Recall Case
            </Button>
          )
        }
      />

      {showForm && (
        <div className="mb-6">
          <OpenRecallCaseForm
            farmId={farmId}
            isSubmitting={openMutation.isPending}
            serverError={openError}
            onSubmit={(payload) => {
              setOpenError(null);
              openMutation.mutate(payload, {
                onSuccess: () => setShowForm(false),
                onError: (err) => setOpenError(asAppError(err)),
              });
            }}
          />
        </div>
      )}

      {isLoading && <LoadingSkeleton rows={4} label="Loading Recall Cases" />}
      {error && <ErrorState error={error} onRetry={() => refetch()} />}
      {data && data.length === 0 && (
        <EmptyState title="No Recall Cases yet." description="Open a Recall Case above if one is needed." />
      )}
      {data && data.length > 0 && (
        <ul className="flex flex-col gap-3">
          {sorted.map((recallCase) => (
            <RecallCaseListItem key={recallCase.recall_case_id} recallCase={recallCase} farmId={farmId} />
          ))}
        </ul>
      )}
    </div>
  );
}
