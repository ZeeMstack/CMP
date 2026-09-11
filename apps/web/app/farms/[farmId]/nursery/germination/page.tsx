"use client";

import { useParams, useSearchParams } from "next/navigation";
import { useState } from "react";

import { Breadcrumbs } from "@/components/Breadcrumbs";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { LoadingSkeleton } from "@/components/LoadingSkeleton";
import { MoveToSeedlingForm } from "@/components/nursery/MoveToSeedlingForm";
import { MoveTrayForm } from "@/components/nursery/MoveTrayForm";
import { NurseryJourney } from "@/components/nursery/NurseryJourney";
import { PlaceTrolleyForm } from "@/components/nursery/PlaceTrolleyForm";
import { RecordOutcomeForm } from "@/components/nursery/RecordOutcomeForm";
import { PageHeader } from "@/components/PageHeader";
import { StatusBadge, type StatusTone } from "@/components/StatusBadge";
import { Button } from "@/components/ui/Button";
import {
  tableBodyDividerClass,
  tableHeadRowClass,
  tableRowHoverClass,
  tableTdClass,
  tableThClass,
  tableWrapperClass,
} from "@/components/ui/table";
import type { GerminationTrayRead } from "@/lib/api/client";
import { AppError } from "@/lib/errors/adapter";
import { useGerminationTrays, usePlaceTray, usePlaceTrolley, useRecordSeedlingEntry } from "@/lib/query/hooks";

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
  const searchParams = useSearchParams();
  // PILOT-UX-001: process continuity from Sowing -- "Move to Germination"
  // hands off here via query params only (reuses this exact route/page,
  // never a second workflow engine), opening the right action directly.
  const contextBatchId = searchParams.get("batchId");
  const [activeAction, setActiveAction] = useState<"trolley" | "tray" | "outcome" | "seedling" | null>(
    () => (searchParams.get("openAction") === "tray" ? "tray" : null),
  );
  const [serverError, setServerError] = useState<string | null>(null);

  const traysQuery = useGerminationTrays(farmId);
  const placeTrolleyMutation = usePlaceTrolley(farmId);
  const placeTrayMutation = usePlaceTray(farmId);
  const recordSeedlingEntryMutation = useRecordSeedlingEntry(farmId);

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
              { label: "Nursery Operations" },
              { label: "Germination" },
            ]}
          />
        }
        actions={
          activeAction === null && (
            <div className="flex flex-wrap gap-2">
              {/* Physical placement actions (secondary) vs. the biological
                  assessment action (primary) -- only one competing "primary"
                  at a time, matching the existing action hierarchy. */}
              <Button type="button" variant="secondary" onClick={() => setActiveAction("trolley")}>
                Place Trolley
              </Button>
              <Button type="button" variant="secondary" onClick={() => setActiveAction("tray")}>
                Move Tray to Germination
              </Button>
              <Button type="button" variant="primary" onClick={() => setActiveAction("outcome")}>
                Record Outcome
              </Button>
              <Button type="button" variant="secondary" onClick={() => setActiveAction("seedling")}>
                Move to Seedling
              </Button>
            </div>
          )
        }
      />
      <NurseryJourney farmId={farmId} current="germination" />

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
          initialBatchId={contextBatchId}
          onSetUpTrolley={() => setActiveAction("trolley")}
          onCancel={closeAction}
          onSubmit={(payload) => {
            setServerError(null);
            placeTrayMutation.mutate(payload, {
              onSuccess: closeAction,
              onError: (error) => setServerError(errorMessage(error)),
            });
          }}
          // PILOT-UX-001 (CTO correction): fast sequential per-tray moves
          // for a multi-tray Batch -- each call is its own independent,
          // idempotent `place_tray` command (backend has no bulk command);
          // this must NOT closeAction after every tray, unlike onSubmit
          // above, so the operator stays on the board for the next tray.
          onSubmitOne={(payload) => placeTrayMutation.mutateAsync(payload)}
        />
      )}

      {activeAction === "outcome" && (
        <RecordOutcomeForm farmId={farmId} onSuccess={closeAction} onCancel={closeAction} />
      )}

      {activeAction === "seedling" && (
        <MoveToSeedlingForm
          farmId={farmId}
          isSubmitting={recordSeedlingEntryMutation.isPending}
          serverError={serverError}
          onCancel={closeAction}
          onSubmit={(payload) => {
            setServerError(null);
            recordSeedlingEntryMutation.mutate(payload, {
              onSuccess: closeAction,
              onError: (error) => setServerError(errorMessage(error)),
            });
          }}
        />
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
            <div className={tableWrapperClass}>
              <table className="w-full text-left text-sm">
                <thead>
                  <tr className={tableHeadRowClass}>
                    <th className={tableThClass}>Batch</th>
                    <th className={tableThClass}>Seed Tray</th>
                    <th className={tableThClass}>Seeds sown</th>
                    <th className={tableThClass}>State</th>
                    <th className={tableThClass}>Placement</th>
                  </tr>
                </thead>
                <tbody className={tableBodyDividerClass}>
                  {traysQuery.data.map((row) => (
                    <tr key={row.tray.id} className={tableRowHoverClass}>
                      <td className={`${tableTdClass} font-medium text-wl-text`}>{row.batch_code}</td>
                      <td className={`${tableTdClass} text-wl-text`}>{row.tray.code}</td>
                      <td className={`${tableTdClass} text-wl-text`}>{row.seeds_sown.toLocaleString()}</td>
                      <td className={tableTdClass}>
                        <StatusBadge label={STATE_LABEL[row.state]} tone={STATE_TONE[row.state]} />
                      </td>
                      <td className={`${tableTdClass} text-wl-text-secondary`}>
                        {row.placement
                          ? `${row.placement.trolley.code} / ${row.placement.chamber.code} / ${row.placement.position.code}`
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
