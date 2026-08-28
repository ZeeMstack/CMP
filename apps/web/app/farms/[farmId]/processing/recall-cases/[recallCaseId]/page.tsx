"use client";

import { useParams } from "next/navigation";
import { useState } from "react";

import { Breadcrumbs } from "@/components/Breadcrumbs";
import { ErrorState } from "@/components/ErrorState";
import { LoadingSkeleton } from "@/components/LoadingSkeleton";
import { PageHeader } from "@/components/PageHeader";
import { CloseRecallCaseForm } from "@/components/processing/CloseRecallCaseForm";
import { AppError } from "@/lib/errors/adapter";
import { useCloseRecallCase, useRecallCase } from "@/lib/query/hooks";

function asAppError(error: unknown): AppError {
  return error instanceof AppError ? error : new AppError("server_error", "Something went wrong. Please try again.");
}

/** PILOT-READY-001: Recall Case detail -- scope, reason, frozen scope
 * (what was contained at the moment the case opened) and live state (what
 * is currently affected), plus a Close action while still open. */
export default function RecallCaseDetailPage() {
  const { farmId, recallCaseId } = useParams<{ farmId: string; recallCaseId: string }>();
  const { data: recallCase, isLoading, error, refetch } = useRecallCase(farmId, recallCaseId);
  const closeMutation = useCloseRecallCase(farmId);
  const [closeError, setCloseError] = useState<AppError | null>(null);

  if (isLoading) return <LoadingSkeleton rows={4} label="Loading Recall Case" />;
  if (error) return <ErrorState error={error} onRetry={() => refetch()} />;
  if (!recallCase) return null;

  return (
    <div>
      <PageHeader
        title={recallCase.code}
        breadcrumbs={
          <Breadcrumbs
            items={[
              { label: "Home", href: `/farms/${farmId}` },
              { label: "Processing", href: `/farms/${farmId}/processing` },
              { label: "Recall Cases", href: `/farms/${farmId}/processing/recall-cases` },
              { label: recallCase.code },
            ]}
          />
        }
      />

      <div className="flex flex-col gap-4">
        <div className="rounded-lg border border-border-subtle bg-surface p-4">
          <span
            className={`inline-flex w-fit items-center rounded-full px-2 py-0.5 text-xs font-medium ${
              recallCase.is_open ? "bg-red-100 text-red-800" : "bg-surface-subtle text-ink-muted"
            }`}
          >
            {recallCase.is_open ? "Open" : "Closed"}
          </span>
          <p className="mt-2 text-sm text-ink">
            {recallCase.reason_code} — {recallCase.reason_text}
          </p>
          <p className="mt-1 text-xs text-ink-muted">Opened {new Date(recallCase.effective_time).toLocaleString()}</p>
          {recallCase.closure && (
            <p className="mt-1 text-xs text-ink-muted">
              Closed {new Date(recallCase.closure.effective_time).toLocaleString()} — {recallCase.closure.close_reason}
            </p>
          )}
        </div>

        <div className="rounded-lg border border-border-subtle bg-surface p-4">
          <h2 className="mb-2 text-sm font-semibold text-ink">Contained at time of opening</h2>
          <pre className="overflow-x-auto whitespace-pre-wrap break-words text-xs text-ink-muted">
            {JSON.stringify(recallCase.frozen_scope, null, 2)}
          </pre>
        </div>

        <div className="rounded-lg border border-border-subtle bg-surface p-4">
          <h2 className="mb-2 text-sm font-semibold text-ink">Currently affected</h2>
          <pre className="overflow-x-auto whitespace-pre-wrap break-words text-xs text-ink-muted">
            {JSON.stringify(recallCase.live_state, null, 2)}
          </pre>
        </div>

        {recallCase.is_open && (
          <CloseRecallCaseForm
            isSubmitting={closeMutation.isPending}
            serverError={closeError}
            onSubmit={(payload) => {
              setCloseError(null);
              closeMutation.mutate(
                { recallCaseId, payload },
                { onError: (err) => setCloseError(asAppError(err)) },
              );
            }}
          />
        )}
      </div>
    </div>
  );
}
