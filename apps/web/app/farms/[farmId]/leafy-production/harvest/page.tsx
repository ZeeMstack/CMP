"use client";

import { useParams, useSearchParams } from "next/navigation";
import { useState } from "react";

import { LinkButton } from "@/components/admin/LinkButton";
import { Breadcrumbs } from "@/components/Breadcrumbs";
import { PageHeader } from "@/components/PageHeader";
import { HarvestablePlatesPanel } from "@/components/leafy/HarvestablePlatesPanel";
import { LeafyHarvestForm } from "@/components/leafy/LeafyHarvestForm";
import { LeafyHarvestHistoryPanel } from "@/components/leafy/LeafyHarvestHistoryPanel";
import { Button } from "@/components/ui/Button";
import { Tabs } from "@/components/ui/Tabs";
import type { CorrectLeafyHarvestSourceLineCreate, HarvestablePlateRead } from "@/lib/api/client";
import { AppError } from "@/lib/errors/adapter";
import { formatDateTime } from "@/lib/format/datetime";
import {
  useCorrectLeafyHarvestSourceLine, useHarvestablePlates, useLeafyHarvests, useLinkWorkItemResult,
  useRecordLeafyHarvest,
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
  const searchParams = useSearchParams();
  // PILOT-OPS-001: a Today-on-the-Farm operational Work Item's "Open
  // Harvest" action carries its own Batch and Work Item id through --
  // see WorkItemRow.tsx. Never required for every other entry point into
  // this page (the harvestable-plates panel).
  const prefillBatchId = searchParams.get("batchId");
  const prefillWorkItemId = searchParams.get("workItemId");
  // PILOT-SCAN-001E: a scanned `batch_carrier_assignment` (Placement) QR
  // identifies ONE specific physical portion of a Batch -- if that Batch is
  // simultaneously split across GH1 and GH2, scanning the GH1 placement
  // must select ONLY that exact source, never "the whole Batch, pick any
  // Plate." `batchId` may also be present (sent alongside, purely to scope
  // the `useHarvestablePlates` read below); `assignmentId` is always the
  // narrower, authoritative context when both are present.
  const prefillAssignmentId = searchParams.get("assignmentId");

  const [tab, setTab] = useState<"harvestable" | "history">("harvestable");
  const [selectedAssignmentIds, setSelectedAssignmentIds] = useState<string[]>([]);
  // Resolved exactly once against this page's own scoped `useHarvestablePlates`
  // read, mirroring GradingPage's/DispatchPage's identical `?...Id=`
  // resolve-once pattern exactly. Never silently falls back to the whole
  // Batch: a released/harvested/foreign/invalid assignment id (anything not
  // present in the CURRENT harvestable-source read, for any reason) is
  // reported via `assignmentContextInvalid`, never guessed or substituted.
  const [assignmentContextResolved, setAssignmentContextResolved] = useState(!prefillAssignmentId);
  const [assignmentContextInvalid, setAssignmentContextInvalid] = useState(false);
  const [recordError, setRecordError] = useState<AppError | null>(null);
  const [recordSuccess, setRecordSuccess] = useState<{
    lotId: string; lotCode: string; batchCode: string; totalHeads: number; totalWeight: string; plateCount: number;
    // HOTFIX-TIME-002: the actual server-authoritative recorded time,
    // never the pre-save browser-generated estimate the Review step showed.
    effectiveTime: string;
    workItemLinkStatus: "linked" | "failed" | null;
    // Present only when a Work Item was involved -- lets a failed link be
    // retried right here, against the exact Harvest result that already
    // succeeded, without the operator ever handling a raw id.
    workItemReconciliation: { workItemId: string; harvestEventId: string; effectiveTime: string } | null;
  } | null>(null);
  const [reconcileError, setReconcileError] = useState<AppError | null>(null);
  const linkWorkItemResultMutation = useLinkWorkItemResult(farmId);
  const [correctingLineId, setCorrectingLineId] = useState<string | null>(null);
  const [correctError, setCorrectError] = useState<AppError | null>(null);
  // PILOT-BLOCKER-010: distinct from `recordMutation.isPending` (which
  // reverts to `false` the instant ANY response -- success, network
  // failure, or definitive rejection -- settles) -- this stays `true` only
  // for a network/server error, where the actual outcome is still unknown,
  // until the operator explicitly submits again. A definitive rejection
  // leaves this `false`, matching existing "editable" semantics.
  const [isResultUnknown, setIsResultUnknown] = useState(false);

  // PILOT-OPS-001: pre-filtered to the Work Item's own Batch when opened
  // with context -- still just the existing farm-wide read, narrowed by
  // its own already-supported `batchId` param, never a second endpoint.
  const harvestablePlatesQuery = useHarvestablePlates(farmId, prefillBatchId ?? undefined);
  const harvestsQuery = useLeafyHarvests(farmId);
  const recordMutation = useRecordLeafyHarvest(farmId);
  const correctMutation = useCorrectLeafyHarvestSourceLine(farmId);

  // Derived, never a frozen snapshot -- always re-read from the (possibly
  // just-invalidated) query data, mirroring leafy-production/page.tsx's
  // own `selectedPlate` derivation exactly.
  const allPlates = harvestablePlatesQuery.data ?? [];

  // Resolve the `?assignmentId=` context exactly once, against this page's
  // own scoped read -- never before the list has actually loaded, and
  // never more than once, so a later refetch (e.g. after recording) can't
  // re-fire this and silently swap the operator's already-selected source.
  // Reusing this SAME read for the safety check is deliberate: it is the
  // authoritative, current-state list of what is actually still harvestable
  // right now, so "not found here" already means released, harvested, on a
  // different farm/tenant, or simply invalid -- no separate lookup, no
  // fabricated distinction between those cases.
  if (!assignmentContextResolved && !harvestablePlatesQuery.isLoading && !harvestablePlatesQuery.isError) {
    const match = allPlates.find((p) => p.current_batch_carrier_assignment_id === prefillAssignmentId);
    if (match) {
      setSelectedAssignmentIds((ids) => (ids.includes(match.current_batch_carrier_assignment_id) ? ids : [...ids, match.current_batch_carrier_assignment_id]));
    } else {
      setAssignmentContextInvalid(true);
    }
    setAssignmentContextResolved(true);
  }

  const selectedPlates: HarvestablePlateRead[] = selectedAssignmentIds
    .map((id) => allPlates.find((p) => p.current_batch_carrier_assignment_id === id))
    .filter((p): p is HarvestablePlateRead => Boolean(p));
  const lockedBatchId = selectedPlates[0]?.batch_id ?? null;
  // Only forward the Work Item id when the Harvest being recorded is
  // genuinely for the Batch that Work Item names -- never blindly attach
  // it to an unrelated Harvest the operator happened to record on this
  // same page visit.
  const workItemIdForSubmit =
    prefillWorkItemId && lockedBatchId && lockedBatchId === prefillBatchId ? prefillWorkItemId : null;

  return (
    <div>
      <PageHeader
        title="Harvest"
        breadcrumbs={
          <Breadcrumbs
            items={[
              { label: "Home", href: `/farms/${farmId}` },
              { label: "Harvest & Post-Harvest" },
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

      {/* PILOT-UX-003: both tab panels stay mounted (toggled with `hidden`,
          never a conditional-render unmount) so switching to "Harvest
          History" and back never wipes an in-progress Harvest draft --
          mirrors PackingPage/GradingPage's identical `hidden` convention. */}
      <div hidden={tab !== "harvestable"} className="flex flex-col gap-4">
        {assignmentContextInvalid && !recordSuccess && (
          <div role="alert" className="flex flex-col gap-2 rounded-md border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900 sm:flex-row sm:items-center sm:justify-between">
            <span>
              The scanned placement is no longer available for Harvest here -- it may have been released, already
              harvested, or belongs to a different farm. Re-scan its current label, or select a source below.
            </span>
            <LinkButton variant="secondary" href={`/farms/${farmId}`}>
              Open Today on the Farm
            </LinkButton>
          </div>
        )}
        {recordSuccess ? (
          <div className="flex flex-col gap-3 rounded-xl border border-wl-border bg-wl-surface-raised p-4">
            <h2 className="font-serif text-base font-semibold text-wl-text">Harvest recorded</h2>
            <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm sm:grid-cols-4">
              <div>
                <dt className="text-wl-text-secondary">Harvest Lot code</dt>
                <dd className="font-medium text-wl-text">{recordSuccess.lotCode}</dd>
              </div>
              <div>
                <dt className="text-wl-text-secondary">Batch</dt>
                <dd className="font-medium text-wl-text">{recordSuccess.batchCode}</dd>
              </div>
              <div>
                <dt className="text-wl-text-secondary">Total heads</dt>
                <dd className="tabular-nums font-medium text-wl-text">{recordSuccess.totalHeads.toLocaleString()}</dd>
              </div>
              <div>
                <dt className="text-wl-text-secondary">Total raw weight</dt>
                <dd className="tabular-nums font-medium text-wl-text">{recordSuccess.totalWeight} kg</dd>
              </div>
              <div>
                <dt className="text-wl-text-secondary">Source Plates</dt>
                <dd className="tabular-nums font-medium text-wl-text">{recordSuccess.plateCount}</dd>
              </div>
              <div>
                <dt className="text-wl-text-secondary">Occurred at</dt>
                <dd className="font-medium text-wl-text">{formatDateTime(recordSuccess.effectiveTime)}</dd>
              </div>
            </dl>
            {/* PILOT-OPS-001: the Harvest above is already authoritative and
                successful -- a failed Work Item link is never a Harvest
                failure, and this Harvest is never repeated to retry it
                (CLAUDE.md "Transaction-backed completion"). */}
            {recordSuccess.workItemLinkStatus === "failed" && recordSuccess.workItemReconciliation && (
              <div className="flex flex-col gap-2 rounded-lg border border-wl-border bg-wl-hold-bg px-3 py-2 text-sm text-wl-hold-fg">
                <p>The linked work item couldn&apos;t be marked complete automatically.</p>
                {reconcileError && <p>{reconcileError.message}</p>}
                <div className="flex flex-wrap gap-2">
                  <Button
                    type="button"
                    variant="secondary"
                    disabled={linkWorkItemResultMutation.isPending}
                    onClick={() => {
                      const reconciliation = recordSuccess.workItemReconciliation;
                      if (!reconciliation) return;
                      setReconcileError(null);
                      linkWorkItemResultMutation.mutate(
                        {
                          workItemId: reconciliation.workItemId,
                          payload: {
                            client_command_id: crypto.randomUUID(),
                            result_entity_type: "harvest_event",
                            result_entity_id: reconciliation.harvestEventId,
                            effective_time: reconciliation.effectiveTime,
                          },
                        },
                        {
                          onSuccess: () => setRecordSuccess((prev) => (prev ? { ...prev, workItemLinkStatus: "linked" } : prev)),
                          onError: (error) => setReconcileError(asAppError(error)),
                        },
                      );
                    }}
                  >
                    {linkWorkItemResultMutation.isPending ? "Retrying…" : "Retry linking work item"}
                  </Button>
                  <LinkButton variant="secondary" href={`/farms/${farmId}`}>
                    Open Today on the Farm
                  </LinkButton>
                </div>
              </div>
            )}
            <div className="flex flex-wrap gap-3">
              <Button
                type="button"
                variant="secondary"
                onClick={() => {
                  setSelectedAssignmentIds([]);
                  setRecordSuccess(null);
                  setRecordError(null);
                }}
              >
                Record another Harvest
              </Button>
              {/* Uses only the actual Harvested Produce Lot id returned by
                  this command -- never a lookup by display code -- and hands
                  it to Grading as a hint it re-resolves against its own
                  scoped read (see GradingPage's `?harvestLotId=` handling). */}
              <LinkButton
                variant="primary"
                href={`/farms/${farmId}/processing/grading?harvestLotId=${recordSuccess.lotId}`}
              >
                Grade this lot
              </LinkButton>
              <LinkButton
                variant="secondary"
                href={`/farms/${farmId}/labels/harvested_produce_lot/${recordSuccess.lotId}`}
              >
                Print Label
              </LinkButton>
            </div>
          </div>
        ) : (
          <>
            {selectedPlates.length > 0 && (
              <LeafyHarvestForm
                plates={selectedPlates}
                onRemovePlate={(assignmentId) =>
                  setSelectedAssignmentIds((ids) => ids.filter((id) => id !== assignmentId))
                }
                isSubmitting={recordMutation.isPending}
                serverError={recordError}
                disableRemove={recordMutation.isPending || isResultUnknown}
                onSubmit={(payload) => {
                  setRecordError(null);
                  setIsResultUnknown(false);
                  recordMutation.mutate(
                    workItemIdForSubmit ? { ...payload, work_item_id: workItemIdForSubmit } : payload,
                    {
                      onSuccess: (result) => {
                        setSelectedAssignmentIds([]);
                        setReconcileError(null);
                        setRecordSuccess({
                          lotId: result.produce_lot_id,
                          lotCode: result.produce_lot_code,
                          batchCode: result.batch_code,
                          totalHeads: result.current_total_whole_unit_count,
                          totalWeight: result.current_total_harvested_weight_kg,
                          plateCount: result.source_lines.length,
                          effectiveTime: result.effective_time,
                          workItemLinkStatus: result.work_item_link_status ?? null,
                          workItemReconciliation: workItemIdForSubmit
                            ? { workItemId: workItemIdForSubmit, harvestEventId: result.id, effectiveTime: result.effective_time }
                            : null,
                        });
                      },
                      onError: (error) => {
                        const appError = asAppError(error);
                        setRecordError(appError);
                        setIsResultUnknown(appError.kind === "network_error" || appError.kind === "server_error");
                      },
                    },
                  );
                }}
              />
            )}
            <HarvestablePlatesPanel
              plates={allPlates}
              selectedAssignmentIds={selectedAssignmentIds}
              lockedBatchId={lockedBatchId}
              isLoading={harvestablePlatesQuery.isLoading}
              disableRemove={recordMutation.isPending || isResultUnknown}
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

      <div hidden={tab !== "history"}>
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
      </div>
    </div>
  );
}
