"use client";

import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { useMemo, useState } from "react";

import { Breadcrumbs } from "@/components/Breadcrumbs";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { BoundedDataRegion } from "@/components/layout/BoundedDataRegion";
import { QueueList, QueueRow } from "@/components/layout/QueueRow";
import { SplitWorkspace } from "@/components/layout/SplitWorkspace";
import { LoadingSkeleton } from "@/components/LoadingSkeleton";
import { GerminationInspector } from "@/components/nursery/GerminationInspector";
import { MoveToSeedlingForm } from "@/components/nursery/MoveToSeedlingForm";
import { MoveTrayForm } from "@/components/nursery/MoveTrayForm";
import { NurseryJourney } from "@/components/nursery/NurseryJourney";
import { PlaceTrolleyForm } from "@/components/nursery/PlaceTrolleyForm";
import { RecordOutcomeForm, type RecordOutcomeSuccessInfo } from "@/components/nursery/RecordOutcomeForm";
import { PageHeader } from "@/components/PageHeader";
import { StatusBadge, type StatusTone } from "@/components/StatusBadge";
import { Button } from "@/components/ui/Button";
import type { GerminationTrayRead } from "@/lib/api/client";
import { AppError } from "@/lib/errors/adapter";
import { germinationPlacementLabel, seedlingEntryLabel } from "@/lib/labels/operationalLabel";
import { printLabels } from "@/lib/labels/printableLabel";
import { usePreparedPrintLabels } from "@/lib/labels/usePreparedPrintLabels";
import {
  useGerminationWorklist,
  usePlaceTray,
  usePlaceTrolley,
  useRecordSeedlingEntry,
  type GerminationWorklistRow,
} from "@/lib/query/hooks";

const PLACEMENT_LABEL: Record<GerminationTrayRead["state"], string> = {
  awaiting_placement: "Awaiting placement",
  elsewhere: "Elsewhere",
  in_germination: "In Germination",
};
const PLACEMENT_TONE: Record<GerminationTrayRead["state"], StatusTone> = {
  awaiting_placement: "attention",
  elsewhere: "neutral",
  in_germination: "active",
};

type StatusFilter = "all" | "needs_placement" | "needs_observation" | "ready_for_seedling";

const STATUS_FILTERS: { value: StatusFilter; label: string }[] = [
  { value: "all", label: "All" },
  { value: "needs_placement", label: "Needs placement" },
  { value: "needs_observation", label: "Needs observation" },
  { value: "ready_for_seedling", label: "Ready for Seedling" },
];

function matchesStatusFilter(row: GerminationWorklistRow, filter: StatusFilter): boolean {
  if (filter === "all") return true;
  if (filter === "needs_placement") return row.nextAction.kind === "place";
  if (filter === "needs_observation") return row.nextAction.kind === "record_outcome";
  return row.nextAction.kind === "move_to_seedling";
}

function errorMessage(error: unknown): string {
  return error instanceof AppError ? error.message : "Something went wrong. Please try again.";
}

type ActiveAction =
  | { kind: "trolley" }
  | { kind: "tray"; trayId?: string }
  // `assignmentId` is omitted for the global/manual header entry points --
  // RecordOutcomeForm/MoveToSeedlingForm fall back to their original
  // operator-driven selection whenever no assignment is frozen.
  | { kind: "outcome"; assignmentId?: string }
  | { kind: "seedling"; assignmentId?: string }
  | null;

type Receipt =
  | {
      kind: "placement";
      batchCode: string;
      trayId: string;
      trayCode: string;
      trolleyCode: string;
      chamberCode: string;
      positionCode: string;
    }
  | ({ kind: "outcome" } & RecordOutcomeSuccessInfo)
  | {
      kind: "seedling";
      batchCode: string;
      trayId: string;
      trayCode: string;
      assignmentId: string;
      tableCode: string;
      livingCount: number;
    }
  | null;

export default function GerminationPage() {
  const { farmId } = useParams<{ farmId: string }>();
  const searchParams = useSearchParams();
  // PILOT-UX-001: process continuity from Sowing -- "Move to Germination"
  // hands off here via query params only (reuses this exact route/page,
  // never a second workflow engine), opening the right action directly.
  const contextBatchId = searchParams.get("batchId");
  const [activeAction, setActiveAction] = useState<ActiveAction>(
    () => (searchParams.get("openAction") === "tray" ? { kind: "tray" } : null),
  );
  const [receipt, setReceipt] = useState<Receipt>(null);
  const [serverError, setServerError] = useState<string | null>(null);
  // PILOT-UX-002B section 9: continuity from a Batch link stays editable --
  // it seeds the filter, it does not lock the worklist to that Batch forever.
  const [batchFilter, setBatchFilter] = useState<string>(contextBatchId ?? "");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [selectedAssignmentId, setSelectedAssignmentId] = useState<string | null>(null);
  const [showMoreActions, setShowMoreActions] = useState(false);

  const worklist = useGerminationWorklist(farmId);
  const rows = worklist.rows;
  const placeTrolleyMutation = usePlaceTrolley(farmId);
  const placeTrayMutation = usePlaceTray(farmId);
  const recordSeedlingEntryMutation = useRecordSeedlingEntry(farmId);

  const batchOptions = useMemo(() => {
    const seen = new Map<string, string>();
    for (const row of rows) seen.set(row.batchId, row.batchCode);
    return Array.from(seen.entries()).map(([id, code]) => ({ id, code }));
  }, [rows]);

  const filteredRows = rows.filter(
    (row) => (!batchFilter || row.batchId === batchFilter) && matchesStatusFilter(row, statusFilter),
  );

  function closeAction() {
    setActiveAction(null);
    setServerError(null);
  }

  function openRowAction(row: GerminationWorklistRow) {
    setServerError(null);
    setReceipt(null);
    if (row.nextAction.kind === "place") setActiveAction({ kind: "tray", trayId: row.trayId });
    else if (row.nextAction.kind === "record_outcome") setActiveAction({ kind: "outcome", assignmentId: row.assignmentId });
    else if (row.nextAction.kind === "move_to_seedling") setActiveAction({ kind: "seedling", assignmentId: row.assignmentId });
  }

  const selectedRow = filteredRows.find((r) => r.assignmentId === selectedAssignmentId) ?? null;

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
        compact
        actions={
          activeAction === null && (
            <Button type="button" variant="secondary" onClick={() => setShowMoreActions((v) => !v)}>
              {showMoreActions ? "Hide manual actions" : "Manual actions"}
            </Button>
          )
        }
      />
      <NurseryJourney farmId={farmId} current="germination" />

      {/* Global/manual entry points -- a compact secondary disclosure so
          they never compete with the worklist rows' own continuity-
          preserving path (PILOT-UX-002B), matching ticket §6.1. */}
      {activeAction === null && showMoreActions && (
        <div className="mb-4 flex flex-wrap gap-2 rounded-lg border border-wl-border bg-wl-surface-sunken p-3">
          <Button type="button" variant="secondary" onClick={() => setActiveAction({ kind: "trolley" })}>
            Place Trolley
          </Button>
          <Button type="button" variant="secondary" onClick={() => setActiveAction({ kind: "tray" })}>
            Move Tray to Germination
          </Button>
          <Button type="button" variant="secondary" onClick={() => setActiveAction({ kind: "outcome" })}>
            Record Outcome (manual)
          </Button>
          <Button type="button" variant="secondary" onClick={() => setActiveAction({ kind: "seedling" })}>
            Move to Seedling (manual)
          </Button>
        </div>
      )}

      {activeAction?.kind === "trolley" && (
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

      {activeAction?.kind === "tray" && (
        <MoveTrayForm
          farmId={farmId}
          isSubmitting={placeTrayMutation.isPending}
          serverError={serverError}
          initialBatchId={contextBatchId}
          initialTrayId={activeAction.trayId ?? null}
          onSetUpTrolley={() => setActiveAction({ kind: "trolley" })}
          onCancel={closeAction}
          onSubmit={(payload) => {
            setServerError(null);
            placeTrayMutation.mutate(payload, {
              onSuccess: (result) => {
                setActiveAction(null);
                setServerError(null);
                setReceipt({
                  kind: "placement",
                  batchCode: result.batch_code,
                  trayId: result.tray.id,
                  trayCode: result.tray.code,
                  trolleyCode: result.trolley.code,
                  chamberCode: result.chamber.code,
                  positionCode: result.position.code,
                });
              },
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

      {activeAction?.kind === "outcome" && (
        <RecordOutcomeForm
          farmId={farmId}
          initialAssignmentId={activeAction.assignmentId}
          onSuccess={(info) => {
            setActiveAction(null);
            setReceipt({ kind: "outcome", ...info });
          }}
          onCancel={closeAction}
        />
      )}

      {activeAction?.kind === "seedling" && (
        <MoveToSeedlingForm
          farmId={farmId}
          initialAssignmentId={activeAction.assignmentId}
          isSubmitting={recordSeedlingEntryMutation.isPending}
          serverError={serverError}
          onCancel={closeAction}
          onSubmit={(payload) => {
            setServerError(null);
            recordSeedlingEntryMutation.mutate(payload, {
              onSuccess: (result) => {
                setActiveAction(null);
                setServerError(null);
                setReceipt({
                  kind: "seedling",
                  batchCode: result.batch_code,
                  trayId: result.tray.id,
                  trayCode: result.tray.code,
                  assignmentId: result.batch_carrier_assignment_id,
                  tableCode: result.seedling_table.code,
                  livingCount: result.starting_living_seedling_count,
                });
              },
              onError: (error) => setServerError(errorMessage(error)),
            });
          }}
        />
      )}

      {activeAction === null && receipt && (
        <GerminationReceiptCard
          farmId={farmId}
          receipt={receipt}
          rows={rows}
          onRefreshWorklist={worklist.refetch}
          onDismiss={() => setReceipt(null)}
          onOpenOutcome={(assignmentId) => {
            setReceipt(null);
            setActiveAction({ kind: "outcome", assignmentId });
          }}
          onOpenSeedling={(assignmentId) => {
            setReceipt(null);
            setActiveAction({ kind: "seedling", assignmentId });
          }}
        />
      )}

      {activeAction === null && !receipt && (
        <>
          {worklist.isLoading && <LoadingSkeleton />}
          {worklist.isError && <ErrorState error={worklist.error} onRetry={() => worklist.refetch()} />}
          {worklist.isSuccess && rows.length === 0 && (
            <EmptyState
              title="No Sown Seed Trays yet"
              description="Trays appear here once a Sowing has been recorded in the Nursery."
            />
          )}
          {worklist.isSuccess && rows.length > 0 && (
            <div className="flex flex-col gap-3">
              {worklist.enrichmentDegraded && (
                <p className="rounded-md border border-wl-border-strong bg-wl-flag-bg px-3 py-2 text-xs text-wl-flag-fg">
                  Some observation/eligibility data could not be loaded — placement is shown, but Next Action may be
                  incomplete for some rows.
                </p>
              )}
              <div className="flex flex-wrap items-center gap-3">
                <label className="flex items-center gap-2 text-sm text-wl-text-secondary">
                  Batch
                  <select
                    value={batchFilter}
                    onChange={(e) => setBatchFilter(e.target.value)}
                    className="min-h-9 rounded-md border border-wl-border bg-wl-surface-raised px-2 text-sm text-wl-text"
                  >
                    <option value="">All batches</option>
                    {batchOptions.map((b) => (
                      <option key={b.id} value={b.id}>
                        {b.code}
                      </option>
                    ))}
                  </select>
                </label>
                <div className="flex flex-wrap gap-1.5">
                  {STATUS_FILTERS.map((f) => (
                    <button
                      key={f.value}
                      type="button"
                      onClick={() => setStatusFilter(f.value)}
                      className={`rounded-md border px-2.5 py-1 text-xs font-medium transition-colors ${
                        statusFilter === f.value
                          ? "border-wl-border-strong bg-wl-brand text-wl-text-on-brand"
                          : "border-wl-border bg-wl-surface-raised text-wl-text-secondary hover:bg-wl-surface-hover"
                      }`}
                    >
                      {f.label}
                    </button>
                  ))}
                </div>
              </div>

              {filteredRows.length === 0 ? (
                <EmptyState
                  title="No Seed Trays match these filters"
                  description="Clear a filter to see more Seed Trays."
                />
              ) : (
                <SplitWorkspace
                  main={
                    <BoundedDataRegion label="Germination queue">
                      <QueueList label="Germination queue">
                        {filteredRows.map((row) => (
                          <QueueRow
                            key={row.assignmentId}
                            isSelected={row.assignmentId === selectedAssignmentId}
                            onSelect={() => setSelectedAssignmentId(row.assignmentId)}
                            title={row.trayCode}
                            context={`Batch ${row.batchCode} · ${row.cropName} / ${row.varietyName}`}
                            status={
                              <div className="flex flex-col items-end gap-1">
                                <StatusBadge label={PLACEMENT_LABEL[row.placementState]} tone={PLACEMENT_TONE[row.placementState]} />
                              </div>
                            }
                          />
                        ))}
                      </QueueList>
                    </BoundedDataRegion>
                  }
                  rail={
                    <GerminationInspector
                      row={selectedRow}
                      farmId={farmId}
                      onOpenAction={openRowAction}
                      onClose={() => setSelectedAssignmentId(null)}
                    />
                  }
                />
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}

export function GerminationReceiptCard({
  farmId,
  receipt,
  rows,
  onRefreshWorklist,
  onDismiss,
  onOpenOutcome,
  onOpenSeedling,
}: {
  farmId: string;
  receipt: NonNullable<Receipt>;
  rows: GerminationWorklistRow[];
  onRefreshWorklist: () => void;
  onDismiss: () => void;
  onOpenOutcome: (assignmentId: string) => void;
  onOpenSeedling: (assignmentId: string) => void;
}) {
  // Hooks must run unconditionally on every render of this component --
  // an empty spec list for receipt kinds with no printable label ("outcome"
  // records no physical placement change) is a no-op for the hook.
  //
  // PILOT-SCAN-001B FINAL CLOSURE (placement identity enforcement):
  // `place_tray`'s own response (`TrayPlacementRead`) does not return a
  // `batch_carrier_assignment_id` -- unlike every other stage's command
  // result. That stable identity already exists (it was opened at Sowing
  // and simply continues through this Movement, unchanged) and is already
  // loaded on this exact page: the Germination worklist read
  // (`useGerminationWorklist` -> `GerminationTrayRead.
  // batch_carrier_assignment_id`) carries it per tray. Looking it up here
  // is using an already-authoritative, already-fetched value -- never
  // inventing one.
  //
  // There is NO fallback to the Carrier's own permanent QR here: an
  // Operational Placement/Stage Label representing Batch + Seed Tray +
  // Germination placement must never silently become a permanent Carrier
  // QR (that would let a later, unrelated Batch's occupancy of the same
  // reused Carrier resolve as if it were THIS placement). If the lookup
  // genuinely fails (the tray is absent from the currently-loaded
  // worklist snapshot), no Operational Placement Label is generated at
  // all -- the render below shows an explicit "not available yet" message
  // with a Refresh action instead. A "Print Carrier Label" action is
  // still offered separately, explicitly labelled as the Carrier's own
  // permanent identity, never presented as this placement's label.
  const placementAssignmentId =
    receipt.kind === "placement" ? rows.find((r) => r.trayId === receipt.trayId)?.assignmentId : undefined;
  const trayLabelSpecs =
    receipt.kind === "placement"
      ? placementAssignmentId
        ? [
            {
              entityType: "batch_carrier_assignment" as const,
              entityId: placementAssignmentId,
              ...germinationPlacementLabel({
                batchCode: receipt.batchCode,
                trayCode: receipt.trayCode,
                chamberCode: receipt.chamberCode,
                trolleyCode: receipt.trolleyCode,
                positionCode: receipt.positionCode,
              }),
            },
          ]
        : []
      : receipt.kind === "seedling"
        ? [
            {
              entityType: "batch_carrier_assignment" as const,
              entityId: receipt.assignmentId,
              ...seedlingEntryLabel({ batchCode: receipt.batchCode, trayCode: receipt.trayCode, tableCode: receipt.tableCode }),
            },
          ]
        : [];
  const trayLabels = usePreparedPrintLabels(farmId, trayLabelSpecs);

  if (receipt.kind === "placement") {
    // PILOT-UX-002B section 10: only the truthful, current next action for
    // this exact Tray/assignment is offered -- read live from the worklist
    // (already invalidated by the placement mutation), never assumed.
    const row = rows.find((r) => r.trayCode === receipt.trayCode && r.batchCode === receipt.batchCode);
    return (
      <div className="flex flex-col gap-3 rounded-lg border border-wl-border-strong bg-wl-grow-bg p-4 text-sm text-wl-grow-fg">
        <p>
          Seed Tray {receipt.trayCode} ({receipt.batchCode}) moved to Trolley {receipt.trolleyCode} / Chamber{" "}
          {receipt.chamberCode} / {receipt.positionCode}.
        </p>
        <div className="flex flex-wrap items-center gap-2">
          {placementAssignmentId ? (
            <Button
              type="button"
              variant="secondary"
              disabled={!trayLabels.labels || trayLabels.labels.length === 0}
              onClick={() => trayLabels.labels && printLabels(trayLabels.labels)}
            >
              {trayLabels.labels ? "Print Tray Label" : "Preparing label…"}
            </Button>
          ) : (
            <>
              <p className="text-sm text-wl-text-secondary">
                Placement identity is not available yet. Refresh before printing.
              </p>
              <Button type="button" variant="secondary" onClick={onRefreshWorklist}>
                Refresh
              </Button>
              {/* A different label type from the Operational Placement Label
                  above -- the Carrier's own permanent identity, never this
                  placement's identity. Kept available so the operator is
                  not left with no printable label at all. */}
              <Link
                href={`/farms/${farmId}/labels/carrier/${receipt.trayId}`}
                className="text-xs font-medium text-wl-text-secondary underline hover:text-wl-text"
              >
                Print Carrier Label instead
              </Link>
            </>
          )}
          {row?.nextAction.kind === "record_outcome" && (
            <Button type="button" variant="primary" onClick={() => onOpenOutcome(row.assignmentId)}>
              Record outcome
            </Button>
          )}
          <Button type="button" variant="secondary" onClick={onDismiss}>
            Continue
          </Button>
        </div>
      </div>
    );
  }

  if (receipt.kind === "outcome") {
    const row = rows.find((r) => r.assignmentId === receipt.assignmentId);
    // Never optimistic: the handoff only appears once the (already
    // invalidated) worklist itself reports this assignment as eligible.
    const showSeedlingHandoff = receipt.assessmentComplete && row?.nextAction.kind === "move_to_seedling";
    return (
      <div className="flex flex-col gap-3 rounded-lg border border-wl-border-strong bg-wl-grow-bg p-4 text-sm text-wl-grow-fg">
        <p>
          Outcome recorded for {receipt.batchCode} — {receipt.trayCode}: {receipt.normalCount} normal /{" "}
          {receipt.abnormalCount} abnormal seedlings ({receipt.assessmentComplete ? "final" : "interim"}).
        </p>
        <div className="flex flex-wrap gap-2">
          {showSeedlingHandoff && (
            <Button type="button" variant="primary" onClick={() => onOpenSeedling(receipt.assignmentId)}>
              Move to Seedling
            </Button>
          )}
          <Button type="button" variant="secondary" onClick={onDismiss}>
            Continue
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3 rounded-lg border border-wl-border-strong bg-wl-grow-bg p-4 text-sm text-wl-grow-fg">
      <p>
        Seed Tray {receipt.trayCode} ({receipt.batchCode}) moved to Seedling Table {receipt.tableCode} —{" "}
        {receipt.livingCount.toLocaleString()} living seedlings.
      </p>
      <div className="flex flex-wrap gap-2">
        <Button
          type="button"
          variant="secondary"
          disabled={!trayLabels.labels || trayLabels.labels.length === 0}
          onClick={() => trayLabels.labels && printLabels(trayLabels.labels)}
        >
          {trayLabels.labels ? "Print Tray Label" : "Preparing label…"}
        </Button>
        <Button type="button" variant="secondary" onClick={onDismiss}>
          Continue
        </Button>
      </div>
    </div>
  );
}
