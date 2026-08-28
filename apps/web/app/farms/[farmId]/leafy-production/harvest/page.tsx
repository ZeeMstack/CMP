"use client";

import { useParams } from "next/navigation";
import { useState } from "react";

import { Breadcrumbs } from "@/components/Breadcrumbs";
import { PageHeader } from "@/components/PageHeader";
import { HarvestablePlatesPanel } from "@/components/leafy/HarvestablePlatesPanel";
import { LeafyHarvestForm } from "@/components/leafy/LeafyHarvestForm";
import { LeafyHarvestHistoryPanel } from "@/components/leafy/LeafyHarvestHistoryPanel";
import { Button } from "@/components/ui/Button";
import { Tabs } from "@/components/ui/Tabs";
import type { CorrectLeafyHarvestSourceLineCreate, HarvestablePlateRead } from "@/lib/api/client";
import { AppError } from "@/lib/errors/adapter";
import {
  useCorrectLeafyHarvestSourceLine, useHarvestablePlates, useLeafyHarvests, useRecordLeafyHarvest,
} from "@/lib/query/hooks";

const TABS = [
  { id: "harvestable", label: "Harvestable Plates" },
  { id: "history", label: "Harvest History" },
] as const;

function asAppError(error: unknown): AppError {
  return error instanceof AppError ? error : new AppError("server_error", "Something went wrong. Please try again.");
}

/** HARVEST-OPS-001 SLICE 2: the Leafy Harvest workspace -- "Harvestable
 * Plates" (default) and "Harvest History" tabs, mirroring `leafy-
 * production/page.tsx`'s own established two-section shape exactly. Does
 * not rename/remove Leafy Production or Production Transfer, which remain
 * their own nav entries. */
export default function LeafyHarvestPage() {
  const { farmId } = useParams<{ farmId: string }>();
  const [tab, setTab] = useState<"harvestable" | "history">("harvestable");
  const [selectedAssignmentIds, setSelectedAssignmentIds] = useState<string[]>([]);
  const [recordError, setRecordError] = useState<AppError | null>(null);
  const [recordSuccess, setRecordSuccess] = useState<{
    lotCode: string; batchCode: string; totalHeads: number; totalWeight: string; plateCount: number;
  } | null>(null);
  const [correctingLineId, setCorrectingLineId] = useState<string | null>(null);
  const [correctError, setCorrectError] = useState<AppError | null>(null);

  const harvestablePlatesQuery = useHarvestablePlates(farmId);
  const harvestsQuery = useLeafyHarvests(farmId);
  const recordMutation = useRecordLeafyHarvest(farmId);
  const correctMutation = useCorrectLeafyHarvestSourceLine(farmId);

  // Derived, never a frozen snapshot -- always re-read from the (possibly
  // just-invalidated) query data, mirroring leafy-production/page.tsx's
  // own `selectedPlate` derivation exactly.
  const allPlates = harvestablePlatesQuery.data ?? [];
  const selectedPlates: HarvestablePlateRead[] = selectedAssignmentIds
    .map((id) => allPlates.find((p) => p.current_batch_carrier_assignment_id === id))
    .filter((p): p is HarvestablePlateRead => Boolean(p));
  const lockedBatchId = selectedPlates[0]?.batch_id ?? null;

  return (
    <div>
      <PageHeader
        title="Harvest"
        breadcrumbs={
          <Breadcrumbs
            items={[
              { label: "Home", href: `/farms/${farmId}` },
              { label: "Batches", href: `/farms/${farmId}/crop-batches` },
              { label: "Leafy Production", href: `/farms/${farmId}/leafy-production` },
              { label: "Harvest" },
            ]}
          />
        }
      />

      <div className="mb-6">
        <Tabs
          tabs={TABS.map(({ id, label }) => ({ id, label }))}
          activeId={tab}
          onChange={(id) => setTab(id as "harvestable" | "history")}
          aria-label="Harvest sections"
        />
      </div>

      {tab === "harvestable" && (
        <div className="flex flex-col gap-4">
          {recordSuccess ? (
            <div className="flex flex-col gap-3 rounded-xl border border-border-subtle bg-surface p-4">
              <h2 className="font-serif text-base font-semibold text-ink">Harvest recorded</h2>
              <dl className="text-sm">
                <div>
                  <dt className="text-ink-muted">Harvest Lot code</dt>
                  <dd className="font-medium text-ink">{recordSuccess.lotCode}</dd>
                </div>
                <div>
                  <dt className="text-ink-muted">Batch</dt>
                  <dd className="font-medium text-ink">{recordSuccess.batchCode}</dd>
                </div>
                <div>
                  <dt className="text-ink-muted">Total heads</dt>
                  <dd className="font-medium text-ink">{recordSuccess.totalHeads.toLocaleString()}</dd>
                </div>
                <div>
                  <dt className="text-ink-muted">Total raw weight</dt>
                  <dd className="font-medium text-ink">{recordSuccess.totalWeight} kg</dd>
                </div>
                <div>
                  <dt className="text-ink-muted">Source Plates</dt>
                  <dd className="font-medium text-ink">{recordSuccess.plateCount}</dd>
                </div>
              </dl>
              <Button
                type="button"
                variant="primary"
                className="self-start"
                onClick={() => {
                  setSelectedAssignmentIds([]);
                  setRecordSuccess(null);
                  setRecordError(null);
                }}
              >
                Done
              </Button>
            </div>
          ) : (
            <>
              {selectedPlates.length > 0 && (
                <LeafyHarvestForm
                  key={selectedAssignmentIds.join(",")}
                  plates={selectedPlates}
                  isSubmitting={recordMutation.isPending}
                  serverError={recordError}
                  onSubmit={(payload) => {
                    setRecordError(null);
                    recordMutation.mutate(payload, {
                      onSuccess: (result) => {
                        setSelectedAssignmentIds([]);
                        setRecordSuccess({
                          lotCode: result.produce_lot_code,
                          batchCode: result.batch_code,
                          totalHeads: result.current_total_whole_unit_count,
                          totalWeight: result.current_total_harvested_weight_kg,
                          plateCount: result.source_lines.length,
                        });
                      },
                      onError: (error) => setRecordError(asAppError(error)),
                    });
                  }}
                />
              )}
              <HarvestablePlatesPanel
                plates={allPlates}
                selectedAssignmentIds={selectedAssignmentIds}
                lockedBatchId={lockedBatchId}
                isLoading={harvestablePlatesQuery.isLoading}
                onAdd={(plate) =>
                  setSelectedAssignmentIds((ids) => [...ids, plate.current_batch_carrier_assignment_id])
                }
                onRemove={(assignmentId) =>
                  setSelectedAssignmentIds((ids) => ids.filter((id) => id !== assignmentId))
                }
              />
            </>
          )}
        </div>
      )}

      {tab === "history" && (
        <LeafyHarvestHistoryPanel
          events={harvestsQuery.data ?? []}
          correctingLineId={correctingLineId}
          isSubmitting={correctMutation.isPending}
          serverError={correctError}
          onCorrect={async (harvestEventId: string, harvestSourceLineId: string, payload: CorrectLeafyHarvestSourceLineCreate) => {
            setCorrectingLineId(harvestSourceLineId);
            setCorrectError(null);
            try {
              await correctMutation.mutateAsync({ harvestEventId, harvestSourceLineId, payload });
              // Only clear on success -- clearing in a blanket `finally`
              // would race with the error branch below and make
              // `correctingLineId === line.id` false by the time this
              // component re-renders, silently dropping the `serverError`
              // that gates the inline alert for this specific line.
              setCorrectingLineId(null);
            } catch (error) {
              setCorrectError(asAppError(error));
              throw error;
            }
          }}
        />
      )}
    </div>
  );
}
