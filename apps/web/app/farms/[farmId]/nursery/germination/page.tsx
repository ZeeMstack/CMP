"use client";

import { useParams } from "next/navigation";
import { useState } from "react";

import { Breadcrumbs } from "@/components/Breadcrumbs";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { LoadingSkeleton } from "@/components/LoadingSkeleton";
import { MoveTrayForm } from "@/components/nursery/MoveTrayForm";
import { PlaceTrolleyForm } from "@/components/nursery/PlaceTrolleyForm";
import { RecordOutcomeForm } from "@/components/nursery/RecordOutcomeForm";
import { PageHeader } from "@/components/PageHeader";
import { StatusBadge, type StatusTone } from "@/components/StatusBadge";
import type { GerminationTrayRead } from "@/lib/api/client";
import { AppError } from "@/lib/errors/adapter";
import { useGerminationTrays, usePlaceTray, usePlaceTrolley } from "@/lib/query/hooks";

const STATE_LABEL: Record<GerminationTrayRead["state"], string> = {
  awaiting_placement: "Awaiting placement",
  elsewhere: "Elsewhere",
  in_germination: "In Germination",
};
const STATE_TONE: Record<GerminationTrayRead["state"], StatusTone> = {
  awaiting_placement: "attention",
  elsewhere: "neutral",
  in_germination: "active",
};

function errorMessage(error: unknown): string {
  return error instanceof AppError ? error.message : "Something went wrong. Please try again.";
}

export default function GerminationPage() {
  const { farmId } = useParams<{ farmId: string }>();
  const [activeAction, setActiveAction] = useState<"trolley" | "tray" | "outcome" | null>(null);
  const [serverError, setServerError] = useState<string | null>(null);

  const traysQuery = useGerminationTrays(farmId);
  const placeTrolleyMutation = usePlaceTrolley(farmId);
  const placeTrayMutation = usePlaceTray(farmId);

  function closeAction() {
    setActiveAction(null);
    setServerError(null);
  }

  return (
    <div>
      <PageHeader
        title="Germination"
        breadcrumbs={
          <Breadcrumbs
            items={[
              { label: "Home", href: `/farms/${farmId}` },
              { label: "Batches", href: `/farms/${farmId}/crop-batches` },
              { label: "Germination" },
            ]}
          />
        }
        actions={
          activeAction === null && (
            <div className="flex gap-3">
              <button
                type="button"
                onClick={() => setActiveAction("trolley")}
                className="min-h-11 rounded-md border border-border-subtle px-4 text-sm font-medium text-ink hover:bg-surface-subtle"
              >
                Place Trolley
              </button>
              <button
                type="button"
                onClick={() => setActiveAction("tray")}
                className="min-h-11 rounded-md border border-border-subtle px-4 text-sm font-medium text-ink hover:bg-surface-subtle"
              >
                Move Tray to Germination
              </button>
              <button
                type="button"
                onClick={() => setActiveAction("outcome")}
                className="min-h-11 rounded-md bg-brand-700 px-4 text-sm font-medium text-white hover:bg-brand-800"
              >
                Record Outcome
              </button>
            </div>
          )
        }
      />

      {activeAction === "trolley" && (
        <PlaceTrolleyForm
          farmId={farmId}
          isSubmitting={placeTrolleyMutation.isPending}
          serverError={serverError}
          onCancel={closeAction}
          onSubmit={(payload) => {
            setServerError(null);
            placeTrolleyMutation.mutate(payload, {
              onSuccess: closeAction,
              onError: (error) => setServerError(errorMessage(error)),
            });
          }}
        />
      )}

      {activeAction === "tray" && (
        <MoveTrayForm
          farmId={farmId}
          isSubmitting={placeTrayMutation.isPending}
          serverError={serverError}
          onCancel={closeAction}
          onSubmit={(payload) => {
            setServerError(null);
            placeTrayMutation.mutate(payload, {
              onSuccess: closeAction,
              onError: (error) => setServerError(errorMessage(error)),
            });
          }}
        />
      )}

      {activeAction === "outcome" && (
        <RecordOutcomeForm farmId={farmId} onSuccess={closeAction} onCancel={closeAction} />
      )}

      {activeAction === null && (
        <>
          {traysQuery.isLoading && <LoadingSkeleton />}
          {traysQuery.isError && <ErrorState error={traysQuery.error} onRetry={() => traysQuery.refetch()} />}
          {traysQuery.isSuccess && traysQuery.data.length === 0 && (
            <EmptyState
              title="No Sown Seed Trays yet"
              description="Trays appear here once a Sowing has been recorded in the Nursery."
            />
          )}
          {traysQuery.isSuccess && traysQuery.data.length > 0 && (
            <div className="overflow-x-auto rounded-lg border border-border-subtle">
              <table className="w-full text-left text-sm">
                <thead className="border-b border-border-subtle bg-surface-subtle text-xs uppercase text-ink-muted">
                  <tr>
                    <th className="px-4 py-2 font-medium">Batch</th>
                    <th className="px-4 py-2 font-medium">Seed Tray</th>
                    <th className="px-4 py-2 font-medium">Seeds sown</th>
                    <th className="px-4 py-2 font-medium">State</th>
                    <th className="px-4 py-2 font-medium">Placement</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border-subtle">
                  {traysQuery.data.map((row) => (
                    <tr key={row.tray.id}>
                      <td className="px-4 py-2 text-ink">{row.batch_code}</td>
                      <td className="px-4 py-2 text-ink">{row.tray.code}</td>
                      <td className="px-4 py-2 text-ink">{row.seeds_sown.toLocaleString()}</td>
                      <td className="px-4 py-2">
                        <StatusBadge label={STATE_LABEL[row.state]} tone={STATE_TONE[row.state]} />
                      </td>
                      <td className="px-4 py-2 text-ink-muted">
                        {row.placement
                          ? `${row.placement.trolley.code} / ${row.placement.chamber.code} / ${row.placement.slot.code}`
                          : "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </div>
  );
}
