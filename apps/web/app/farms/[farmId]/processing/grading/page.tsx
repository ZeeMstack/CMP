"use client";

import { useParams } from "next/navigation";
import { useState } from "react";

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
  useGradingEvents, useHarvestedProduceLotBalance, useHarvestedProduceLots, useLocationsTree, useRecordGrading,
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
 * own established two-section shape exactly. */
export default function GradingPage() {
  const { farmId } = useParams<{ farmId: string }>();
  const [tab, setTab] = useState<"grade" | "history">("grade");
  const [selectedLot, setSelectedLot] = useState<HarvestedProduceLotRead | null>(null);
  const [recordError, setRecordError] = useState<AppError | null>(null);
  const [recordSuccess, setRecordSuccess] = useState<{ sourceCode: string; outputCodes: string[] } | null>(null);

  const lotsQuery = useHarvestedProduceLots(farmId);
  const locationsQuery = useLocationsTree(farmId);
  const balanceQuery = useHarvestedProduceLotBalance(farmId, selectedLot?.id ?? null);
  const gradingEventsQuery = useGradingEvents(farmId);
  const recordMutation = useRecordGrading(farmId);

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

      {tab === "grade" && (
        <div className="flex flex-col gap-4">
          {recordSuccess ? (
            <div className="flex flex-col gap-3 rounded-xl border border-border-subtle bg-surface p-4">
              <h2 className="font-serif text-base font-semibold text-ink">Grading recorded</h2>
              <p className="text-sm text-ink">
                Source <span className="font-medium">{recordSuccess.sourceCode}</span> graded into{" "}
                <span className="font-medium">{recordSuccess.outputCodes.join(", ")}</span>
              </p>
              <Button
                type="button"
                variant="primary"
                className="self-start"
                onClick={() => {
                  setSelectedLot(null);
                  setRecordSuccess(null);
                  setRecordError(null);
                }}
              >
                Done
              </Button>
            </div>
          ) : (
            <>
              {selectedLot && (
                <GradingForm
                  key={selectedLot.id}
                  sourceLot={selectedLot}
                  balance={balanceQuery.data}
                  locations={locationsQuery.data ?? []}
                  isSubmitting={recordMutation.isPending}
                  serverError={recordError}
                  onSubmit={(payload) => {
                    setRecordError(null);
                    recordMutation.mutate(payload, {
                      onSuccess: (result) => {
                        setRecordSuccess({
                          sourceCode: result.source_produce_lot_code,
                          outputCodes: result.outputs.map((o) => o.code),
                        });
                        setSelectedLot(null);
                      },
                      onError: (error) => setRecordError(asAppError(error)),
                    });
                  }}
                />
              )}
              <HarvestedProduceLotPicker
                lots={lotsQuery.data ?? []}
                selectedId={selectedLot?.id ?? null}
                isLoading={lotsQuery.isLoading}
                onSelect={(lot) => setSelectedLot(lot)}
              />
            </>
          )}
        </div>
      )}

      {tab === "history" && (
        <GradingHistoryPanel farmId={farmId} events={gradingEventsQuery.data ?? []} isLoading={gradingEventsQuery.isLoading} />
      )}
    </div>
  );
}
