"use client";

import { useParams } from "next/navigation";
import { useState } from "react";

import { Breadcrumbs } from "@/components/Breadcrumbs";
import { PageHeader } from "@/components/PageHeader";
import { GradedProduceLotSourcePanel } from "@/components/processing/GradedProduceLotSourcePanel";
import { PackingForm } from "@/components/processing/PackingForm";
import { PackingHistoryPanel } from "@/components/processing/PackingHistoryPanel";
import { Button } from "@/components/ui/Button";
import { Tabs } from "@/components/ui/Tabs";
import type { GradedProduceLotRead } from "@/lib/api/client";
import { AppError } from "@/lib/errors/adapter";
import {
  useGradeVersionLabelMap, useGradedProduceLots, usePackingEvents, useRecallCases, useRecordPacking,
} from "@/lib/query/hooks";

const TABS = [
  { id: "pack", label: "Pack Graded Lots" },
  { id: "history", label: "Packing History" },
] as const;

function asAppError(error: unknown): AppError {
  return error instanceof AppError ? error : new AppError("server_error", "Something went wrong. Please try again.");
}

/** POSTHARVEST-OPS-001G: the Packing workspace -- "Pack Graded Lots"
 * (default) and "Packing History" tabs, mirroring `leafy-production/harvest/
 * page.tsx`'s own established two-section shape exactly. */
export default function PackingPage() {
  const { farmId } = useParams<{ farmId: string }>();
  const [tab, setTab] = useState<"pack" | "history">("pack");
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [recordError, setRecordError] = useState<AppError | null>(null);
  const [recordSuccess, setRecordSuccess] = useState<{ code: string; inputCodes: string[] } | null>(null);

  const gplsQuery = useGradedProduceLots(farmId);
  const { labels: gradeLabels } = useGradeVersionLabelMap();
  const recallCasesQuery = useRecallCases(farmId);
  const packingEventsQuery = usePackingEvents(farmId);
  const recordMutation = useRecordPacking(farmId);

  const allLots = gplsQuery.data ?? [];
  const selectedLots: GradedProduceLotRead[] = selectedIds
    .map((id) => allLots.find((l) => l.id === id))
    .filter((l): l is GradedProduceLotRead => Boolean(l));
  const lockedCropId = selectedLots[0]?.crop.id ?? null;

  return (
    <div>
      <PageHeader
        title="Packing"
        breadcrumbs={
          <Breadcrumbs
            items={[
              { label: "Home", href: `/farms/${farmId}` },
              { label: "Processing", href: `/farms/${farmId}/processing` },
              { label: "Packing" },
            ]}
          />
        }
      />

      <div className="mb-6">
        <Tabs
          tabs={TABS.map(({ id, label }) => ({ id, label }))}
          activeId={tab}
          onChange={(id) => setTab(id as "pack" | "history")}
          aria-label="Packing sections"
        />
      </div>

      {tab === "pack" && (
        <div className="flex flex-col gap-4">
          {recordSuccess ? (
            <div className="flex flex-col gap-3 rounded-xl border border-border-subtle bg-surface p-4">
              <h2 className="font-serif text-base font-semibold text-ink">Packing recorded</h2>
              <p className="text-sm text-ink">
                <span className="font-medium">{recordSuccess.code}</span> packed from{" "}
                <span className="font-medium">{recordSuccess.inputCodes.join(", ")}</span>
              </p>
              <Button
                type="button"
                variant="primary"
                className="self-start"
                onClick={() => {
                  setSelectedIds([]);
                  setRecordSuccess(null);
                  setRecordError(null);
                }}
              >
                Done
              </Button>
            </div>
          ) : (
            <>
              {selectedLots.length > 0 && (
                <PackingForm
                  key={selectedIds.join(",")}
                  farmId={farmId}
                  lots={selectedLots}
                  isSubmitting={recordMutation.isPending}
                  serverError={recordError}
                  onSubmit={(payload) => {
                    setRecordError(null);
                    recordMutation.mutate(payload, {
                      onSuccess: (result) => {
                        setRecordSuccess({
                          code: result.finished_goods_lot.code,
                          inputCodes: result.input_lines.map((l) => l.graded_produce_lot_code),
                        });
                        setSelectedIds([]);
                      },
                      onError: (error) => setRecordError(asAppError(error)),
                    });
                  }}
                />
              )}
              <GradedProduceLotSourcePanel
                lots={allLots}
                farmId={farmId}
                gradeLabels={gradeLabels}
                recallCases={recallCasesQuery.data}
                selectedIds={selectedIds}
                lockedCropId={lockedCropId}
                isLoading={gplsQuery.isLoading}
                onAdd={(lot) => setSelectedIds((ids) => [...ids, lot.id])}
                onRemove={(lotId) => setSelectedIds((ids) => ids.filter((id) => id !== lotId))}
              />
            </>
          )}
        </div>
      )}

      {tab === "history" && (
        <PackingHistoryPanel farmId={farmId} events={packingEventsQuery.data ?? []} isLoading={packingEventsQuery.isLoading} />
      )}
    </div>
  );
}
