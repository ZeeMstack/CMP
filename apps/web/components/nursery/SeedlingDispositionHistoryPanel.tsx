"use client";

import { useState } from "react";

import { CorrectDispositionForm } from "@/components/nursery/CorrectDispositionForm";
import { ErrorState } from "@/components/ErrorState";
import { LoadingSkeleton } from "@/components/LoadingSkeleton";
import { Button } from "@/components/ui/Button";
import type { SeedlingDispositionEventRead } from "@/lib/api/client";
import { AppError } from "@/lib/errors/adapter";
import { useCorrectSeedlingDisposition, useSeedlingDispositionHistory } from "@/lib/query/hooks";

function errorMessage(error: unknown): string {
  return error instanceof AppError ? error.message : "Something went wrong. Please try again.";
}

const KIND_LABEL: Record<SeedlingDispositionEventRead["event_kind"], string> = {
  REDUCTION: "Recorded",
  REVERSAL: "Reversed",
};

/** NURSERY-OPS-003B section 55: shows the full, un-collapsed event history
 * for one Tray -- REDUCTION and REVERSAL rows are never merged or hidden,
 * and a REDUCTION already reversed shows its linkage rather than offering
 * "Correct" again (a REDUCTION may be reversed at most once; a REVERSAL can
 * never itself be corrected -- section 1.C). */
export function SeedlingDispositionHistoryPanel({
  farmId, seedlingEntryId, onClose,
}: {
  farmId: string;
  seedlingEntryId: string;
  onClose: () => void;
}) {
  const [correctingEventId, setCorrectingEventId] = useState<string | null>(null);
  const [serverError, setServerError] = useState<string | null>(null);

  const historyQuery = useSeedlingDispositionHistory(farmId, seedlingEntryId);
  const correctMutation = useCorrectSeedlingDisposition(farmId);

  const events = historyQuery.data?.events ?? [];
  const reversedTargetIds = new Set(
    events.filter((e) => e.reverses_event_id).map((e) => e.reverses_event_id as string),
  );
  const correctingTarget = events.find((e) => e.id === correctingEventId) ?? null;

  return (
    <div className="flex flex-col gap-4 rounded-xl border border-border-subtle bg-surface p-4">
      <div className="flex items-center justify-between">
        <h2 className="font-serif text-base font-semibold text-ink">Disposition history</h2>
        <Button type="button" variant="secondary" onClick={onClose}>
          Close
        </Button>
      </div>

      {historyQuery.isLoading && <LoadingSkeleton />}
      {historyQuery.isError && <ErrorState error={historyQuery.error} onRetry={() => historyQuery.refetch()} />}

      {historyQuery.isSuccess && (
        <>
          <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm sm:grid-cols-3">
            <div>
              <dt className="text-ink-muted">Starting living seedlings</dt>
              <dd className="font-medium text-ink">{historyQuery.data.starting_living_seedling_count.toLocaleString()}</dd>
            </div>
            <div>
              <dt className="text-ink-muted">Current living seedlings</dt>
              <dd className="font-medium text-ink">{historyQuery.data.current_living_seedling_count.toLocaleString()}</dd>
            </div>
          </dl>

          {events.length === 0 ? (
            <p className="text-sm text-ink-muted">No dispositions have been recorded for this Tray yet.</p>
          ) : (
            <div className="overflow-x-auto rounded-xl border border-border-subtle">
              <table className="w-full text-left text-sm">
                <thead className="border-b border-border-subtle bg-surface-subtle text-xs uppercase text-ink-muted">
                  <tr>
                    <th className="px-4 py-2 font-medium">When</th>
                    <th className="px-4 py-2 font-medium">Kind</th>
                    <th className="px-4 py-2 font-medium">Reason</th>
                    <th className="px-4 py-2 font-medium">Quantity</th>
                    <th className="px-4 py-2 font-medium">Note</th>
                    <th className="px-4 py-2 font-medium">Linkage</th>
                    <th className="px-4 py-2 font-medium" />
                  </tr>
                </thead>
                <tbody className="divide-y divide-border-subtle">
                  {events.map((event) => {
                    const correctable = event.event_kind === "REDUCTION" && !reversedTargetIds.has(event.id);
                    return (
                      <tr key={event.id} className="hover:bg-surface-subtle">
                        <td className="px-4 py-2 text-ink-muted">{new Date(event.effective_time).toLocaleString()}</td>
                        <td className="px-4 py-2 text-ink">{KIND_LABEL[event.event_kind]}</td>
                        <td className="px-4 py-2 text-ink">{event.reason_code}</td>
                        <td className="px-4 py-2 text-ink">{event.quantity_delta}</td>
                        <td className="px-4 py-2 text-ink-muted">{event.note ?? "—"}</td>
                        <td className="px-4 py-2 text-ink-muted">
                          {event.reverses_event_id && "Reverses a prior entry"}
                          {event.corrects_event_id && !event.reverses_event_id && "Replaces a corrected entry"}
                          {!event.reverses_event_id && !event.corrects_event_id && "—"}
                        </td>
                        <td className="px-4 py-2">
                          {correctable && (
                            <Button
                              type="button"
                              variant="secondary"
                              onClick={() => {
                                setServerError(null);
                                setCorrectingEventId(event.id);
                              }}
                            >
                              Correct
                            </Button>
                          )}
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

      {correctingTarget && (
        <CorrectDispositionForm
          farmId={farmId}
          target={correctingTarget}
          isSubmitting={correctMutation.isPending}
          serverError={serverError}
          onCancel={() => {
            setCorrectingEventId(null);
            setServerError(null);
          }}
          onSubmit={(payload) => {
            setServerError(null);
            correctMutation.mutate(
              { eventId: correctingTarget.id, payload },
              {
                onSuccess: () => setCorrectingEventId(null),
                onError: (error) => setServerError(errorMessage(error)),
              },
            );
          }}
        />
      )}
    </div>
  );
}
