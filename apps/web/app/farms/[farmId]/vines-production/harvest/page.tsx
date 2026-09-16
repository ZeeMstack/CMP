"use client";

import { useParams } from "next/navigation";
import { useState } from "react";

import { LinkButton } from "@/components/admin/LinkButton";
import { Breadcrumbs } from "@/components/Breadcrumbs";
import { PageHeader } from "@/components/PageHeader";
import { RecordVinesHarvestForm } from "@/components/vines/RecordVinesHarvestForm";
import { VinesHarvestableSourcesPanel } from "@/components/vines/VinesHarvestableSourcesPanel";
import { VinesHarvestHistoryPanel } from "@/components/vines/VinesHarvestHistoryPanel";
import { Tabs } from "@/components/ui/Tabs";
import { Button } from "@/components/ui/Button";
import type { CorrectVinesHarvestSourceLineCreate, VinesHarvestableSourceRead } from "@/lib/api/client";
import { AppError } from "@/lib/errors/adapter";
import { formatDateTime } from "@/lib/format/datetime";
import {
  useCorrectVinesHarvestSourceLine, useVinesHarvestableSources, useVinesHarvests, useRecordVinesHarvest,
} from "@/lib/query/hooks";

const TABS = [
  { id: "harvestable", label: "Harvestable Sources" },
  { id: "history", label: "Harvest History" },
] as const;

function asAppError(error: unknown): AppError {
  return error instanceof AppError ? error : new AppError("server_error", "Something went wrong. Please try again.");
}

/** VINES-OPS-003: the Vines Harvest workspace -- "Harvestable Sources"
 * (default) and "Harvest History" tabs, mirroring `leafy-production/harvest/
 * page.tsx`'s own established two-section shape exactly. Does not rename/
 * remove Vines Production or the 001B Transfer workflow, which remain their
 * own nav entries. */
export default function VinesHarvestPage() {
  const { farmId } = useParams<{ farmId: string }>();
  const [tab, setTab] = useState<"harvestable" | "history">("harvestable");
  const [selectedGutterIds, setSelectedGutterIds] = useState<string[]>([]);
  const [recordError, setRecordError] = useState<AppError | null>(null);
  const [recordSuccess, setRecordSuccess] = useState<{
    lotId: string; lotCode: string; batchCode: string; totalWeight: string; gutterCount: number;
    // HOTFIX-TIME-002: the authoritative server-recorded effective time,
    // never the pre-save browser-clock placeholder.
    effectiveTime: string;
  } | null>(null);
  const [correctingLineId, setCorrectingLineId] = useState<string | null>(null);
  const [correctError, setCorrectError] = useState<AppError | null>(null);
  // PILOT-BLOCKER-010: mirrors leafy-production/harvest/page.tsx's identical
  // guard exactly -- distinct from `recordMutation.isPending`, this stays
  // `true` only while a network/server error leaves the actual outcome
  // unknown, never for a definitive rejection.
  const [isResultUnknown, setIsResultUnknown] = useState(false);

  const harvestableSourcesQuery = useVinesHarvestableSources(farmId);
  const harvestsQuery = useVinesHarvests(farmId);
  const recordMutation = useRecordVinesHarvest(farmId);
  const correctMutation = useCorrectVinesHarvestSourceLine(farmId);

  const allSources = harvestableSourcesQuery.data ?? [];
  const selectedSources: VinesHarvestableSourceRead[] = selectedGutterIds
    .map((id) => allSources.find((s) => s.gutter_id === id))
    .filter((s): s is VinesHarvestableSourceRead => Boolean(s));
  const lockedBatchId = selectedSources[0]?.batch_id ?? null;

  return (
    <div>
      <PageHeader
        title="Vines Harvest"
        breadcrumbs={
          <Breadcrumbs
            items={[
              { label: "Home", href: `/farms/${farmId}` },
              { label: "Vines Production" },
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
          aria-label="Vines Harvest sections"
        />
      </div>

      {/* PILOT-UX-006: both tab panels stay mounted (toggled with `hidden`,
          never a conditional-render unmount) so switching to "Harvest
          History" and back never wipes an in-progress Harvest draft --
          mirrors leafy-production/harvest/page.tsx's identical `hidden`
          convention. */}
      <div hidden={tab !== "harvestable"} className="flex flex-col gap-4">
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
                  <dt className="text-ink-muted">Total raw weight</dt>
                  <dd className="font-medium text-ink">{recordSuccess.totalWeight} kg</dd>
                </div>
                <div>
                  <dt className="text-ink-muted">Source Gutters</dt>
                  <dd className="font-medium text-ink">{recordSuccess.gutterCount}</dd>
                </div>
                <div>
                  <dt className="text-ink-muted">Occurred at</dt>
                  <dd className="font-medium text-ink">{formatDateTime(recordSuccess.effectiveTime)}</dd>
                </div>
              </dl>
              <p className="text-xs text-ink-muted">
                Living plant count and Grow Bag capacity are unchanged -- these Gutters remain fully harvestable
                again later.
              </p>
              <div className="flex flex-wrap gap-3">
                <Button
                  type="button"
                  variant="secondary"
                  onClick={() => {
                    setSelectedGutterIds([]);
                    setRecordSuccess(null);
                    setRecordError(null);
                  }}
                >
                  Record another Harvest
                </Button>
                {/* Uses only the actual Harvested Produce Lot id returned by
                    this command -- never a lookup by display code -- and hands
                    it to Grading as a hint it re-resolves against its own
                    scoped read (mirrors leafy-production/harvest/page.tsx's
                    identical "Grade this lot" handoff exactly). */}
                <LinkButton
                  variant="primary"
                  href={`/farms/${farmId}/processing/grading?harvestLotId=${recordSuccess.lotId}`}
                >
                  Grade this lot
                </LinkButton>
              </div>
            </div>
          ) : (
            <>
              {selectedSources.length > 0 && (
                <RecordVinesHarvestForm
                  sources={selectedSources}
                  onRemoveSource={(gutterId) => setSelectedGutterIds((ids) => ids.filter((id) => id !== gutterId))}
                  isSubmitting={recordMutation.isPending}
                  serverError={recordError}
                  disableRemove={recordMutation.isPending || isResultUnknown}
                  onSubmit={(payload) => {
                    setRecordError(null);
                    setIsResultUnknown(false);
                    recordMutation.mutate(payload, {
                      onSuccess: (result) => {
                        setSelectedGutterIds([]);
                        setRecordSuccess({
                          lotId: result.produce_lot_id,
                          lotCode: result.produce_lot_code,
                          batchCode: result.batch_code,
                          totalWeight: result.current_total_harvested_weight_kg,
                          gutterCount: result.source_lines.length,
                          effectiveTime: result.effective_time,
                        });
                      },
                      onError: (error) => {
                        const appError = asAppError(error);
                        setRecordError(appError);
                        setIsResultUnknown(appError.kind === "network_error" || appError.kind === "server_error");
                      },
                    });
                  }}
                />
              )}
              <VinesHarvestableSourcesPanel
                sources={allSources}
                selectedGutterIds={selectedGutterIds}
                lockedBatchId={lockedBatchId}
                isLoading={harvestableSourcesQuery.isLoading}
                disableRemove={recordMutation.isPending || isResultUnknown}
                onAdd={(source) => setSelectedGutterIds((ids) => [...ids, source.gutter_id])}
                onRemove={(gutterId) => setSelectedGutterIds((ids) => ids.filter((id) => id !== gutterId))}
              />
            </>
          )}
      </div>

      <div hidden={tab !== "history"}>
        <VinesHarvestHistoryPanel
          events={harvestsQuery.data ?? []}
          correctingLineId={correctingLineId}
          isSubmitting={correctMutation.isPending}
          serverError={correctError}
          onCorrect={async (harvestEventId: string, harvestSourceLineId: string, payload: CorrectVinesHarvestSourceLineCreate) => {
            setCorrectingLineId(harvestSourceLineId);
            setCorrectError(null);
            try {
              await correctMutation.mutateAsync({ harvestEventId, harvestSourceLineId, payload });
              setCorrectingLineId(null);
            } catch (error) {
              setCorrectError(asAppError(error));
              throw error;
            }
          }}
        />
      </div>
    </div>
  );
}
