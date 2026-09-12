"use client";

import { useParams, useSearchParams } from "next/navigation";
import { useState } from "react";

import { LinkButton } from "@/components/admin/LinkButton";
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
 * page.tsx`'s own established two-section shape exactly.
 *
 * PILOT-UX-002C: both tab panels stay mounted (toggled with `hidden`) so
 * switching to "Packing History" and back never wipes the in-progress
 * draft. `PackingForm` is no longer remounted when `selectedIds` changes --
 * see that component's own note -- so add/remove no longer resets the
 * Pack Specification/Version, Finished Goods Lot code, or any already-typed
 * quantity. The optional `?gradedLotIds=` deep link (the actual handoff
 * from a successful Grading) is resolved against this page's own scoped
 * `useGradedProduceLots` read: any id not found, or not sharing the Crop of
 * the first valid one, is reported in `droppedContextLots` and left out of
 * the draft rather than silently dropped without explanation. */
export default function PackingPage() {
  const { farmId } = useParams<{ farmId: string }>();
  const searchParams = useSearchParams();
  const contextGradedLotIds = searchParams.get("gradedLotIds");

  const [tab, setTab] = useState<"pack" | "history">("pack");
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [contextResolved, setContextResolved] = useState(!contextGradedLotIds);
  const [droppedContextLots, setDroppedContextLots] = useState<string[]>([]);
  const [recordError, setRecordError] = useState<AppError | null>(null);
  const [recordSuccess, setRecordSuccess] = useState<{
    id: string;
    code: string;
    inputCodes: string[];
    packedWeightKg: string;
    packageCount: number;
  } | null>(null);

  const gplsQuery = useGradedProduceLots(farmId);
  const { labels: gradeLabels } = useGradeVersionLabelMap();
  const recallCasesQuery = useRecallCases(farmId);
  const packingEventsQuery = usePackingEvents(farmId);
  const recordMutation = useRecordPacking(farmId);

  const allLots = gplsQuery.data ?? [];

  // Resolve the `?gradedLotIds=` context exactly once, against this page's
  // own scoped read -- ids are validated (found in this Farm) and Crop-
  // compatible with each other before being preselected; anything that
  // fails either check is reported, never silently dropped.
  if (!contextResolved && !gplsQuery.isLoading && !gplsQuery.isError) {
    const requestedIds = contextGradedLotIds ? contextGradedLotIds.split(",").filter(Boolean) : [];
    const found = requestedIds.map((id) => ({ id, lot: allLots.find((l) => l.id === id) }));
    const firstCropId = found.find((f) => f.lot)?.lot?.crop.id ?? null;
    const valid = found.filter((f) => f.lot && f.lot.crop.id === firstCropId).map((f) => f.id);
    const dropped = found.filter((f) => !f.lot || f.lot.crop.id !== firstCropId).map((f) => f.id);
    if (valid.length > 0) setSelectedIds(valid);
    if (dropped.length > 0) setDroppedContextLots(dropped);
    setContextResolved(true);
  }

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

      <div hidden={tab !== "pack"} className="flex flex-col gap-4">
        {droppedContextLots.length > 0 && (
          <p role="alert" className="rounded-md border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900">
            {droppedContextLots.length === 1
              ? "One requested Graded Produce Lot could not be added (not found in this Farm, or a different Crop)."
              : `${droppedContextLots.length} requested Graded Produce Lots could not be added (not found in this Farm, or a different Crop).`}
          </p>
        )}

        {recordSuccess ? (
          <div className="flex flex-col gap-3 rounded-xl border border-border-subtle bg-surface p-4">
            <h2 className="font-serif text-base font-semibold text-ink">Packing recorded</h2>
            <p className="text-sm text-ink">
              <span className="font-medium">{recordSuccess.code}</span> packed from{" "}
              <span className="font-medium">{recordSuccess.inputCodes.join(", ")}</span>
            </p>
            <p className="text-sm text-ink-muted">
              {recordSuccess.packedWeightKg} kg · {recordSuccess.packageCount} packages
            </p>
            <div className="flex flex-wrap gap-3">
              <Button
                type="button"
                variant="secondary"
                onClick={() => {
                  setSelectedIds([]);
                  setDroppedContextLots([]);
                  setRecordSuccess(null);
                  setRecordError(null);
                }}
              >
                Pack more Lots
              </Button>
              <LinkButton
                variant="primary"
                href={`/farms/${farmId}/processing/cold-storage?finishedGoodsLotId=${recordSuccess.id}`}
              >
                Place in cold store
              </LinkButton>
            </div>
          </div>
        ) : (
          <>
            {selectedLots.length > 0 && (
              <PackingForm
                farmId={farmId}
                lots={selectedLots}
                onRemoveLot={(lotId) => setSelectedIds((ids) => ids.filter((id) => id !== lotId))}
                isSubmitting={recordMutation.isPending}
                serverError={recordError}
                onSubmit={(payload) => {
                  setRecordError(null);
                  recordMutation.mutate(payload, {
                    onSuccess: (result) => {
                      setRecordSuccess({
                        id: result.finished_goods_lot.id,
                        code: result.finished_goods_lot.code,
                        inputCodes: result.input_lines.map((l) => l.graded_produce_lot_code),
                        packedWeightKg: result.finished_goods_lot.net_packed_weight_kg,
                        packageCount: result.finished_goods_lot.package_count,
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
              isError={gplsQuery.isError}
              error={gplsQuery.error}
              onRetry={() => gplsQuery.refetch()}
              onAdd={(lot) => setSelectedIds((ids) => [...ids, lot.id])}
            />
          </>
        )}
      </div>

      <div hidden={tab !== "history"}>
        <PackingHistoryPanel farmId={farmId} events={packingEventsQuery.data ?? []} isLoading={packingEventsQuery.isLoading} />
      </div>
    </div>
  );
}
