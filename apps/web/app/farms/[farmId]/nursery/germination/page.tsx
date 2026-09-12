"use client";

import { useParams, useSearchParams } from "next/navigation";
import { Fragment, useMemo, useState } from "react";

import { Breadcrumbs } from "@/components/Breadcrumbs";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { LoadingSkeleton } from "@/components/LoadingSkeleton";
import { MoveToSeedlingForm } from "@/components/nursery/MoveToSeedlingForm";
import { MoveTrayForm } from "@/components/nursery/MoveTrayForm";
import { NurseryJourney } from "@/components/nursery/NurseryJourney";
import { PlaceTrolleyForm } from "@/components/nursery/PlaceTrolleyForm";
import { RecordOutcomeForm, type RecordOutcomeSuccessInfo } from "@/components/nursery/RecordOutcomeForm";
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
import {
  useGerminationWorklist,
  usePlaceTray,
  usePlaceTrolley,
  useRecordSeedlingEntry,
  type GerminationNextAction,
  type GerminationObservationStatus,
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
const OBSERVATION_LABEL: Record<GerminationObservationStatus, string> = {
  not_observed: "Not observed",
  interim: "Interim",
  final: "Final",
};
const OBSERVATION_TONE: Record<GerminationObservationStatus, StatusTone> = {
  not_observed: "neutral",
  interim: "attention",
  final: "active",
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

function nextActionLabel(action: GerminationNextAction): string | null {
  switch (action.kind) {
    case "place":
      return "Move to Germination";
    case "record_outcome":
      return action.isUpdate ? "Update outcome" : "Record outcome";
    case "move_to_seedling":
      return "Move to Seedling";
    case "none":
      return null;
  }
}

function errorMessage(error: unknown): string {
  return error instanceof AppError ? error.message : "Something went wrong. Please try again.";
}

function formatDateTime(iso: string | null): string | null {
  if (!iso) return null;
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
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
      trayCode: string;
      trolleyCode: string;
      chamberCode: string;
      positionCode: string;
    }
  | ({ kind: "outcome" } & RecordOutcomeSuccessInfo)
  | { kind: "seedling"; batchCode: string; trayCode: string; tableCode: string; livingCount: number }
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
  const [expandedRows, setExpandedRows] = useState<Set<string>>(new Set());

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

  function toggleExpanded(assignmentId: string) {
    setExpandedRows((prev) => {
      const next = new Set(prev);
      if (next.has(assignmentId)) next.delete(assignmentId);
      else next.add(assignmentId);
      return next;
    });
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
                  at a time, matching the existing action hierarchy. These
                  remain manual/global entry points; the worklist rows below
                  are the primary, continuity-preserving path (PILOT-UX-002B). */}
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
          )
        }
      />
      <NurseryJourney farmId={farmId} current="germination" />

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
                  trayCode: result.tray.code,
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
          receipt={receipt}
          rows={rows}
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
                <div className={tableWrapperClass}>
                  <table className="w-full text-left text-sm">
                    <thead>
                      <tr className={tableHeadRowClass}>
                        <th className={tableThClass} />
                        <th className={tableThClass}>Batch</th>
                        <th className={tableThClass}>Seed Tray</th>
                        <th className={tableThClass}>Placement</th>
                        <th className={tableThClass}>Observation</th>
                        <th className={tableThClass}>Next action</th>
                      </tr>
                    </thead>
                    <tbody className={tableBodyDividerClass}>
                      {filteredRows.map((row) => {
                        const expanded = expandedRows.has(row.assignmentId);
                        const actionLabel = nextActionLabel(row.nextAction);
                        const latestObservedAt = formatDateTime(row.latestObservedAt);
                        return (
                          <Fragment key={row.assignmentId}>
                            <tr className={tableRowHoverClass}>
                              <td className={tableTdClass}>
                                <button
                                  type="button"
                                  onClick={() => toggleExpanded(row.assignmentId)}
                                  aria-expanded={expanded}
                                  aria-label={expanded ? "Hide details" : "Show details"}
                                  className="text-wl-text-secondary hover:text-wl-text"
                                >
                                  {expanded ? "▾" : "▸"}
                                </button>
                              </td>
                              <td className={`${tableTdClass} font-medium text-wl-text`}>{row.batchCode}</td>
                              <td className={tableTdClass}>
                                <div className="font-medium text-wl-text">{row.trayCode}</div>
                                <div className="text-xs text-wl-text-secondary">
                                  {row.cropName} / {row.varietyName}
                                </div>
                              </td>
                              <td className={tableTdClass}>
                                <StatusBadge
                                  label={PLACEMENT_LABEL[row.placementState]}
                                  tone={PLACEMENT_TONE[row.placementState]}
                                />
                                <div className="mt-1 text-xs text-wl-text-secondary">{row.placementLabel ?? "—"}</div>
                              </td>
                              <td className={tableTdClass}>
                                <StatusBadge
                                  label={OBSERVATION_LABEL[row.observationStatus]}
                                  tone={OBSERVATION_TONE[row.observationStatus]}
                                />
                                <div className="mt-1 text-xs text-wl-text-secondary">
                                  {row.normalCount === null && row.abnormalCount === null
                                    ? "—"
                                    : `${row.normalCount ?? 0} normal / ${row.abnormalCount ?? 0} abnormal`}
                                </div>
                              </td>
                              <td className={tableTdClass}>
                                {actionLabel ? (
                                  <Button type="button" variant="primary" onClick={() => openRowAction(row)}>
                                    {actionLabel}
                                  </Button>
                                ) : (
                                  <span className="text-xs text-wl-text-secondary">—</span>
                                )}
                              </td>
                            </tr>
                            {expanded && (
                              <tr className="bg-wl-surface-sunken">
                                <td className={tableTdClass} />
                                <td className={`${tableTdClass} text-xs text-wl-text-secondary`} colSpan={5}>
                                  <dl className="grid grid-cols-2 gap-x-4 gap-y-1 sm:grid-cols-4">
                                    <div>
                                      <dt>Seed Lot</dt>
                                      <dd className="font-medium text-wl-text">{row.seedLotCode}</dd>
                                    </div>
                                    <div>
                                      <dt>Seeds sown</dt>
                                      <dd className="font-medium text-wl-text">{row.seedsSown.toLocaleString()}</dd>
                                    </div>
                                    <div>
                                      <dt>Sown Sites</dt>
                                      <dd className="font-medium text-wl-text">{row.sownSiteCount ?? "Not recorded"}</dd>
                                    </div>
                                    <div>
                                      <dt>Prior observations</dt>
                                      <dd className="font-medium text-wl-text">{row.historicalSnapshotCount}</dd>
                                    </div>
                                    {latestObservedAt && (
                                      <div>
                                        <dt>Latest observed at</dt>
                                        <dd className="font-medium text-wl-text">{latestObservedAt}</dd>
                                      </div>
                                    )}
                                  </dl>
                                </td>
                              </tr>
                            )}
                          </Fragment>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}

function GerminationReceiptCard({
  receipt,
  rows,
  onDismiss,
  onOpenOutcome,
  onOpenSeedling,
}: {
  receipt: NonNullable<Receipt>;
  rows: GerminationWorklistRow[];
  onDismiss: () => void;
  onOpenOutcome: (assignmentId: string) => void;
  onOpenSeedling: (assignmentId: string) => void;
}) {
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
        <div className="flex flex-wrap gap-2">
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
      <Button type="button" variant="secondary" className="self-start" onClick={onDismiss}>
        Continue
      </Button>
    </div>
  );
}
