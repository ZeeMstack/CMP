"use client";

import { useParams, useSearchParams } from "next/navigation";
import { useState } from "react";

import { LinkButton } from "@/components/admin/LinkButton";
import { Breadcrumbs } from "@/components/Breadcrumbs";
import { PageHeader } from "@/components/PageHeader";
import { GradingForm } from "@/components/processing/GradingForm";
import { GradingHistoryPanel } from "@/components/processing/GradingHistoryPanel";
import { HarvestedProduceLotPicker } from "@/components/processing/HarvestedProduceLotPicker";
import { Button } from "@/components/ui/Button";
import { Tabs } from "@/components/ui/Tabs";
import type { HarvestedProduceLotRead } from "@/lib/api/client";
import { AppError } from "@/lib/errors/adapter";
import {
  useGradingEvents, useHarvestedProduceLotBalance, useHarvestedProduceLots, useLocationsTree, useRecallCases,
  useRecordGrading,
} from "@/lib/query/hooks";

const TABS = [
  { id: "grade", label: "Grade a Lot" },
  { id: "history", label: "Grading History" },
] as const;

function asAppError(error: unknown): AppError {
  return error instanceof AppError ? error : new AppError("server_error", "Something went wrong. Please try again.");
}

/** POSTHARVEST-OPS-001G: the Grading workspace -- "Grade a Lot" (default)
 * and "Grading History" tabs, mirroring `leafy-production/harvest/page.tsx`'s
 * own established two-section shape exactly.
 *
 * PILOT-UX-002C: both tab panels stay mounted at all times (toggled with
 * `hidden`, never a conditional-render unmount) so switching to "Grading
 * History" to check something and back never wipes the operator's own
 * in-progress source selection or output/disposition draft -- a
 * non-authoritative UI change must never reset the form. The optional
 * `?harvestLotId=` deep link (e.g. handed off from a future Harvest success
 * screen) is only ever a hint: the actual Lot is resolved by matching it
 * against this page's own scoped `useHarvestedProduceLots` read, never
 * trusted or navigated-to directly. */
export default function GradingPage() {
  const { farmId } = useParams<{ farmId: string }>();
  const searchParams = useSearchParams();
  const contextHarvestLotId = searchParams.get("harvestLotId");

  const [tab, setTab] = useState<"grade" | "history">("grade");
  const [selectedLot, setSelectedLot] = useState<HarvestedProduceLotRead | null>(null);
  const [contextResolved, setContextResolved] = useState(!contextHarvestLotId);
  const [contextInvalid, setContextInvalid] = useState(false);
  const [defaultProcessingLocationId, setDefaultProcessingLocationId] = useState("");
  const [recordError, setRecordError] = useState<AppError | null>(null);
  const [recordSuccess, setRecordSuccess] = useState<{
    sourceCode: string;
    outputs: { id: string; code: string; weightKg: string }[];
  } | null>(null);

  const lotsQuery = useHarvestedProduceLots(farmId);
  const recallCasesQuery = useRecallCases(farmId);
  const locationsQuery = useLocationsTree(farmId);
  const balanceQuery = useHarvestedProduceLotBalance(farmId, selectedLot?.id ?? null);
  const gradingEventsQuery = useGradingEvents(farmId);
  const recordMutation = useRecordGrading(farmId);

  const lots = lotsQuery.data ?? [];

  // Resolve the `?harvestLotId=` context exactly once, against this page's
  // own scoped read -- never before the list has actually loaded, and never
  // more than once, so a later refetch (e.g. after recording) can't re-fire
  // this and silently swap the operator's already-selected source.
  if (!contextResolved && !lotsQuery.isLoading && !lotsQuery.isError) {
    const match = lots.find((l) => l.id === contextHarvestLotId);
    if (match) {
      setSelectedLot(match);
    } else {
      setContextInvalid(true);
    }
    setContextResolved(true);
  }

  return (
    <div>
      <PageHeader
        title="Grading"
        breadcrumbs={
          <Breadcrumbs
            items={[
              { label: "Home", href: `/farms/${farmId}` },
              { label: "Processing", href: `/farms/${farmId}/processing` },
              { label: "Grading" },
            ]}
          />
        }
      />

      <div className="mb-6">
        <Tabs
          tabs={TABS.map(({ id, label }) => ({ id, label }))}
          activeId={tab}
          onChange={(id) => setTab(id as "grade" | "history")}
          aria-label="Grading sections"
        />
      </div>

      <div hidden={tab !== "grade"} className="flex flex-col gap-4">
        {contextInvalid && (
          <p role="alert" className="rounded-md border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900">
            The requested Harvest Lot could not be found in this Farm. Select a Lot from the queue below.
          </p>
        )}

        {recordSuccess ? (
          <div className="flex flex-col gap-3 rounded-xl border border-border-subtle bg-surface p-4">
            <h2 className="font-serif text-base font-semibold text-ink">Grading recorded</h2>
            <p className="text-sm text-ink">
              Source <span className="font-medium">{recordSuccess.sourceCode}</span> graded into{" "}
              <span className="font-medium">{recordSuccess.outputs.map((o) => o.code).join(", ")}</span>
            </p>
            <ul className="flex flex-col gap-1 text-sm text-ink-muted">
              {recordSuccess.outputs.map((o) => (
                <li key={o.id}>
                  {o.code} — {o.weightKg} kg
                </li>
              ))}
            </ul>
            <div className="flex flex-wrap gap-3">
              <Button
                type="button"
                variant="secondary"
                onClick={() => {
                  setSelectedLot(null);
                  setRecordSuccess(null);
                  setRecordError(null);
                }}
              >
                Grade another Lot
              </Button>
              <LinkButton
                variant="primary"
                href={`/farms/${farmId}/processing/packing?gradedLotIds=${recordSuccess.outputs.map((o) => o.id).join(",")}`}
              >
                Pack these outputs
              </LinkButton>
            </div>
          </div>
        ) : (
          <>
            {selectedLot && (
              <GradingForm
                key={selectedLot.id}
                sourceLot={selectedLot}
                balance={balanceQuery.data}
                isBalanceError={balanceQuery.isError}
                locations={locationsQuery.data ?? []}
                defaultProcessingLocationId={defaultProcessingLocationId}
                onProcessingLocationChange={setDefaultProcessingLocationId}
                isSubmitting={recordMutation.isPending}
                serverError={recordError}
                onSubmit={(payload) => {
                  setRecordError(null);
                  recordMutation.mutate(payload, {
                    onSuccess: (result) => {
                      setRecordSuccess({
                        sourceCode: result.source_produce_lot_code,
                        outputs: result.outputs.map((o) => ({ id: o.id, code: o.code, weightKg: o.original_received_weight_kg })),
                      });
                      setSelectedLot(null);
                    },
                    onError: (error) => setRecordError(asAppError(error)),
                  });
                }}
                onChangeSource={() => setSelectedLot(null)}
              />
            )}
            <HarvestedProduceLotPicker
              lots={lots}
              farmId={farmId}
              recallCases={recallCasesQuery.data}
              selectedId={selectedLot?.id ?? null}
              isLoading={lotsQuery.isLoading}
              isError={lotsQuery.isError}
              error={lotsQuery.error}
              onRetry={() => lotsQuery.refetch()}
              onSelect={(lot) => {
                setContextInvalid(false);
                setSelectedLot(lot);
              }}
            />
          </>
        )}
      </div>

      <div hidden={tab !== "history"}>
        <GradingHistoryPanel farmId={farmId} events={gradingEventsQuery.data ?? []} isLoading={gradingEventsQuery.isLoading} />
      </div>
    </div>
  );
}
