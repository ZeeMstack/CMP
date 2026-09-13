"use client";

import { useParams } from "next/navigation";
import { Fragment } from "react";

import { Breadcrumbs } from "@/components/Breadcrumbs";
import { ErrorState } from "@/components/ErrorState";
import { PageHeader } from "@/components/PageHeader";
import { QualityActionPanel } from "@/components/store-inventory/QualityActionPanel";
import { Button } from "@/components/ui/Button";
import type {
  QualityDispositionCorrectionCreate, QualityDispositionCreate, QualityPartialCorrectionCreate,
  QualityPartialDispositionCreate, QualityWorkQueueRowRead,
} from "@/lib/api/client";
import { AppError } from "@/lib/errors/adapter";
import {
  useApplyQualityDispositionToPartialQuantity, useCohortStorageBreakdown, useCorrectQualityDisposition,
  useCorrectQualityDispositionForPartialQuantity, useFarms, useQualityWorkQueue, useRecordQualityDisposition,
  useUoms,
} from "@/lib/query/hooks";
import { useQualityCommandDraft } from "@/lib/store-inventory/qualityCommandDraft";

function asAppError(error: unknown): AppError {
  return error instanceof AppError ? error : new AppError("server_error", "Something went wrong. Please try again.");
}

/** Current restriction badge -- always paired with its own text label
 * (CLAUDE.md/PILOT-UX-003: never color alone). Purely a display label over
 * the backend's own `current_state`; never a second source of truth for
 * which actions are legal (`ORDINARY_ACTIONS` below owns that). */
const RESTRICTION_BADGES: Record<string, { label: string; className: string }> = {
  RECEIVED_QUARANTINED: { label: "Quarantined", className: "bg-wl-hold-bg text-wl-hold-fg" },
  RELEASED: { label: "Released", className: "bg-wl-grow-bg text-wl-grow-fg" },
  HELD: { label: "Held", className: "bg-wl-hold-bg text-wl-hold-fg" },
  HOLD_RELEASED: { label: "Hold released", className: "bg-wl-grow-bg text-wl-grow-fg" },
  REJECTED: { label: "Rejected", className: "bg-wl-flag-bg text-wl-flag-fg" },
};

/** UX-only mirror of the backend's frozen state machine (docs/domain/
 * STORE_INVENTORY_MODEL.md §11) -- purely which action buttons to offer.
 * The backend independently, authoritatively re-validates every command;
 * this table never substitutes for that. */
const ORDINARY_ACTIONS: Record<string, string[]> = {
  RECEIVED_QUARANTINED: ["RELEASED", "HELD", "REJECTED"],
  RELEASED: ["HELD", "REJECTED"],
  HELD: ["HOLD_RELEASED", "REJECTED"],
  HOLD_RELEASED: ["HELD", "REJECTED"],
  REJECTED: [],
};

/** STORE-INV-002A.2: the Quality work queue -- Release / Hold / Reject /
 * Hold-Release, "Apply disposition to part of quantity" (never "Split
 * Cohort"), "Correct decision", and "Correct decision for part of
 * quantity" (CTO closure pass §3 -- e.g. un-rejecting part of a REJECTED
 * cohort; never exposed for the automatic opening RECEIVED_QUARANTINED
 * fact, and never for implicit RELEASED with no human decision yet).
 *
 * PILOT-BLOCKER-005 F04/F05/F06: an ORDINARY (or PARTIAL) action never
 * requires the row to already have a `current_event_id` -- implicit
 * RELEASED material with no prior Quality event can still open its first
 * Hold/Reject. A CORRECT/PARTIAL_CORRECT action instead captures
 * `target_event_id` once, the moment it opens (`useQualityCommandDraft`),
 * and that captured id remains authoritative for the whole life of the
 * draft -- a later work-queue refetch never silently substitutes a newer
 * event. If the backend rejects it as stale, the draft shows a conflict
 * and requires the operator to deliberately close and reopen a fresh
 * action; it never auto-retargets. */
export default function StoreInventoryQualityPage() {
  const { farmId } = useParams<{ farmId: string }>();
  const queueQuery = useQualityWorkQueue();
  const draft = useQualityCommandDraft();
  const farmsQuery = useFarms();
  const farmNameById = new Map((farmsQuery.data ?? []).map((f) => [f.id, f.name]));
  const uomsQuery = useUoms();
  const uomCodeById = new Map((uomsQuery.data ?? []).map((u) => [u.id, u.code]));

  const dispositionMutation = useRecordQualityDisposition();
  const partialMutation = useApplyQualityDispositionToPartialQuantity();
  const correctMutation = useCorrectQualityDisposition();
  const partialCorrectMutation = useCorrectQualityDispositionForPartialQuantity();
  // STORE-INV-002B: eligible physical buckets for the currently-open
  // PARTIAL/PARTIAL_CORRECT action only -- undefined (disabled) otherwise.
  const bucketsCohortId =
    draft.context?.kind === "PARTIAL" || draft.context?.kind === "PARTIAL_CORRECT" ? draft.context.cohortId : undefined;
  const bucketsQuery = useCohortStorageBreakdown(bucketsCohortId);

  const rows = [...(queueQuery.data ?? [])].sort(
    (a, b) => new Date(b.receipt_received_at).getTime() - new Date(a.receipt_received_at).getTime(),
  );
  // F08: a background refetch failure must never be presented as "nothing
  // needs attention" -- `data` (react-query) is retained across a failed
  // refetch, so an error alongside existing rows means "stale, refresh
  // failed", never "empty".
  const hasQueueData = queueQuery.data !== undefined;

  return (
    <div>
      <PageHeader
        title="Quality"
        description="Release, Hold, Reject, and correct Quality decisions for received material."
        breadcrumbs={
          <Breadcrumbs
            items={[
              { label: "Home", href: `/farms/${farmId}` },
              { label: "Store & Inventory", href: `/farms/${farmId}/store-inventory` },
              { label: "Quality" },
            ]}
          />
        }
      />

      {queueQuery.isLoading ? (
        <p className="text-sm text-wl-text-secondary">Loading…</p>
      ) : queueQuery.isError && !hasQueueData ? (
        <ErrorState error={queueQuery.error} onRetry={() => queueQuery.refetch()} />
      ) : (
        <>
          {/* PILOT-BLOCKER-008 A6 (Astra R03/F08): a refresh failure must
              never be presented as "Nothing currently needs Quality
              attention" merely because the CACHED list happens to be
              empty -- this banner's visibility depends only on
              `queueQuery.isError`, never on `rows.length`, unlike the old
              ternary ordering which only showed it when rows existed. */}
          {queueQuery.isError && (
            <p className="mb-3 flex flex-wrap items-center gap-2 rounded-md border border-wl-border-strong bg-wl-flag-bg px-3 py-2 text-xs text-wl-flag-fg">
              Could not refresh the Quality queue -- showing the last known data.
              <button type="button" className="font-medium underline" onClick={() => queueQuery.refetch()}>
                Retry
              </button>
            </p>
          )}
          {rows.length === 0 ? (
            // A stale/error state with a genuinely empty cache already got
            // its banner above -- never additionally claim "Nothing
            // currently needs Quality attention", which is only true for a
            // SUCCESSFUL empty result.
            !queueQuery.isError && <p className="text-sm text-wl-text">Nothing currently needs Quality attention.</p>
          ) : (
          <div className="overflow-x-auto rounded-xl border border-wl-border bg-wl-surface-raised">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-wl-border bg-wl-surface-sunken text-left text-xs font-medium text-wl-text-secondary">
                  <th className="p-3">Item / Lot</th>
                  <th className="p-3">Farm</th>
                  <th className="p-3 text-right">Quantity</th>
                  <th className="p-3">Current restriction</th>
                  <th className="p-3">Action</th>
                </tr>
              </thead>
              <tbody>
            {rows.map((row: QualityWorkQueueRowRead) => {
              const actions = ORDINARY_ACTIONS[row.current_state] ?? [];
              // A human decision to correct only exists once at least one
              // event has been recorded -- implicit RELEASED (zero events)
              // has nothing to correct, exactly like RECEIVED_QUARANTINED.
              const canCorrect = row.current_event_id !== null && row.current_state !== "RECEIVED_QUARANTINED";
              const isOpenForThisRow = draft.context?.cohortId === row.inventory_quantity_cohort_id;
              // PILOT-BLOCKER-008 A2: once a command is submitting or its
              // outcome is uncertain, opening ANY action -- on this row or
              // another -- must never silently discard its frozen id/
              // payload. Only a resolved draft (editing/conflict/closed)
              // may be abandoned by opening something else.
              const blockNewAction = draft.outcome === "submitting" || draft.outcome === "uncertain";
              const badge = RESTRICTION_BADGES[row.current_state] ?? { label: row.current_state, className: "bg-wl-surface-sunken text-wl-text-secondary" };
              const uomCode = uomCodeById.get(row.base_uom_id);
              return (
                <Fragment key={row.inventory_quantity_cohort_id}>
                <tr className={`border-b border-wl-border last:border-0 hover:bg-wl-surface-hover ${isOpenForThisRow ? "bg-wl-brand-subtle" : ""}`}>
                  <td className="p-3 align-top">
                    <p className="font-medium text-wl-text">{row.item_name}</p>
                    <p className="text-xs text-wl-text-secondary">
                      {row.manufacturer_lot_reference ? `Lot ${row.manufacturer_lot_reference}` : `Receipt ${row.receipt_code}`}
                      {row.expiry_date ? ` · Expires ${row.expiry_date}` : ""}
                    </p>
                  </td>
                  <td className="p-3 align-top text-xs text-wl-text-secondary">
                    {farmNameById.get(row.received_at_farm_id) ?? `Farm ${row.received_at_farm_id.slice(0, 8)}`}
                  </td>
                  <td className="p-3 align-top text-right tabular-nums text-wl-text">
                    {uomCode ? `${row.balance} ${uomCode}` : row.balance}
                  </td>
                  <td className="p-3 align-top">
                    <span className={`inline-flex w-fit items-center rounded-full px-2 py-0.5 text-xs font-medium ${badge.className}`}>
                      {badge.label}
                    </span>
                  </td>
                  <td className="p-3 align-top">
                    <div className="flex flex-col items-start gap-1.5">
                      <div className="flex flex-wrap gap-2">
                        {actions.map((disposition) => (
                          <Button
                            key={disposition}
                            type="button"
                            variant="secondary"
                            disabled={blockNewAction}
                            onClick={() => {
                              draft.open({
                                cohortId: row.inventory_quantity_cohort_id, kind: "ORDINARY", targetEventId: null,
                                observedState: row.current_state, disposition,
                              });
                            }}
                          >
                            {disposition === "RELEASED" ? "Release"
                              : disposition === "HELD" ? "Hold"
                              : disposition === "REJECTED" ? "Reject"
                              : "Hold Release"}
                          </Button>
                        ))}
                      </div>
                      {/* Exception-path actions (part-of-quantity / decision
                          corrections) are deliberately lighter-weight than the
                          ordinary dispositions above -- these are the uncommon
                          case, not competing equally for attention. */}
                      <div className="flex flex-wrap gap-x-3 gap-y-1">
                        {actions.length > 0 && (
                          <button
                            type="button"
                            className="text-xs font-medium text-wl-text-secondary hover:text-wl-brand hover:underline disabled:cursor-not-allowed disabled:opacity-50 disabled:no-underline"
                            disabled={blockNewAction}
                            onClick={() => {
                              draft.open({
                                cohortId: row.inventory_quantity_cohort_id, kind: "PARTIAL", targetEventId: null,
                                observedState: row.current_state,
                              });
                            }}
                          >
                            Apply to part of quantity
                          </button>
                        )}
                        {canCorrect && (
                          <button
                            type="button"
                            className="text-xs font-medium text-wl-text-secondary hover:text-wl-brand hover:underline disabled:cursor-not-allowed disabled:opacity-50 disabled:no-underline"
                            disabled={blockNewAction}
                            onClick={() => {
                              // F06: captured once, now, from this row --
                              // never re-read from a later refetch.
                              draft.open({
                                cohortId: row.inventory_quantity_cohort_id, kind: "CORRECT",
                                targetEventId: row.current_event_id, observedState: row.current_state,
                              });
                            }}
                          >
                            Correct decision
                          </button>
                        )}
                        {canCorrect && (
                          <button
                            type="button"
                            className="text-xs font-medium text-wl-text-secondary hover:text-wl-brand hover:underline disabled:cursor-not-allowed disabled:opacity-50 disabled:no-underline"
                            disabled={blockNewAction}
                            onClick={() => {
                              draft.open({
                                cohortId: row.inventory_quantity_cohort_id, kind: "PARTIAL_CORRECT",
                                targetEventId: row.current_event_id, observedState: row.current_state,
                              });
                            }}
                          >
                            Correct decision for part of quantity
                          </button>
                        )}
                      </div>
                    </div>
                  </td>
                </tr>

                {isOpenForThisRow && draft.context && (
                  <tr>
                    <td colSpan={5} className="border-b border-wl-border bg-wl-surface-sunken p-3 last:border-0">
                      <QualityActionPanel
                        row={row}
                        kind={draft.context.kind}
                        disposition={draft.context.kind === "ORDINARY" ? draft.context.disposition : undefined}
                        legalReplacements={
                          draft.context.kind === "PARTIAL" ? actions
                            : draft.context.kind === "CORRECT" ? ["RELEASED", "HELD", "REJECTED", "HOLD_RELEASED"]
                            : undefined
                        }
                        buckets={
                          draft.context.kind === "PARTIAL" || draft.context.kind === "PARTIAL_CORRECT"
                            ? bucketsQuery.data?.buckets
                            : undefined
                        }
                        bucketsError={
                          (draft.context.kind === "PARTIAL" || draft.context.kind === "PARTIAL_CORRECT") && bucketsQuery.isError
                            ? asAppError(bucketsQuery.error)
                            : null
                        }
                        onRetryBuckets={() => bucketsQuery.refetch()}
                        isSubmitting={
                          dispositionMutation.isPending || partialMutation.isPending || correctMutation.isPending ||
                          partialCorrectMutation.isPending
                        }
                        serverError={draft.error}
                        commandOutcome={draft.outcome}
                        onCancel={draft.close}
                        onRetry={() => {
                          const context = draft.context;
                          if (!context) return;
                          const frozen = draft.retry();
                          if (!frozen) return;
                          const { payload, generation } = frozen;
                          const variables = { farmId: row.received_at_farm_id, itemId: row.inventory_item_id };
                          if (context.kind === "ORDINARY") {
                            dispositionMutation.mutate(
                              { payload: payload as QualityDispositionCreate, ...variables },
                              {
                                onSuccess: () => draft.handleSuccess(generation),
                                onError: (err) => draft.handleError(asAppError(err), generation),
                              },
                            );
                          } else if (context.kind === "PARTIAL") {
                            partialMutation.mutate(
                              { payload: payload as QualityPartialDispositionCreate, ...variables },
                              {
                                onSuccess: () => draft.handleSuccess(generation),
                                onError: (err) => draft.handleError(asAppError(err), generation),
                              },
                            );
                          } else if (context.kind === "CORRECT") {
                            correctMutation.mutate(
                              { payload: payload as QualityDispositionCorrectionCreate, ...variables },
                              {
                                onSuccess: () => draft.handleSuccess(generation),
                                onError: (err) => draft.handleError(asAppError(err), generation),
                              },
                            );
                          } else {
                            partialCorrectMutation.mutate(
                              { payload: payload as QualityPartialCorrectionCreate, ...variables },
                              {
                                onSuccess: () => draft.handleSuccess(generation),
                                onError: (err) => draft.handleError(asAppError(err), generation),
                              },
                            );
                          }
                        }}
                        onSubmitOrdinary={({ reason, effectiveTime }) => {
                          if (draft.context?.kind !== "ORDINARY") return;
                          const { payload, generation } = draft.submit({
                            inventory_quantity_cohort_id: row.inventory_quantity_cohort_id,
                            disposition: draft.context.disposition, effective_time: effectiveTime,
                            reason: reason.trim() || null,
                          });
                          dispositionMutation.mutate(
                            { payload: payload as QualityDispositionCreate, farmId: row.received_at_farm_id, itemId: row.inventory_item_id },
                            {
                              onSuccess: () => draft.handleSuccess(generation),
                              onError: (err) => draft.handleError(asAppError(err), generation),
                            },
                          );
                        }}
                        onSubmitPartial={({ quantity, disposition, reason, effectiveTime, custodyLocationId }) => {
                          const { payload, generation } = draft.submit({
                            inventory_quantity_cohort_id: row.inventory_quantity_cohort_id, quantity, disposition,
                            effective_time: effectiveTime, reason: reason.trim() || null,
                            custody_location_id: custodyLocationId,
                          });
                          partialMutation.mutate(
                            { payload: payload as QualityPartialDispositionCreate, farmId: row.received_at_farm_id, itemId: row.inventory_item_id },
                            {
                              onSuccess: () => draft.handleSuccess(generation),
                              onError: (err) => draft.handleError(asAppError(err), generation),
                            },
                          );
                        }}
                        onSubmitCorrect={({ reason, replacementDisposition, effectiveTime }) => {
                          if (draft.context?.kind !== "CORRECT" || !draft.context.targetEventId) return;
                          const { payload, generation } = draft.submit({
                            inventory_quantity_cohort_id: row.inventory_quantity_cohort_id,
                            target_event_id: draft.context.targetEventId, reason,
                            replacement_disposition: replacementDisposition, effective_time: effectiveTime,
                          });
                          correctMutation.mutate(
                            { payload: payload as QualityDispositionCorrectionCreate, farmId: row.received_at_farm_id, itemId: row.inventory_item_id },
                            {
                              onSuccess: () => draft.handleSuccess(generation),
                              onError: (err) => draft.handleError(asAppError(err), generation),
                            },
                          );
                        }}
                        onSubmitPartialCorrect={({ quantity, correctedDisposition, reason, effectiveTime, custodyLocationId }) => {
                          if (draft.context?.kind !== "PARTIAL_CORRECT" || !draft.context.targetEventId) return;
                          const { payload, generation } = draft.submit({
                            inventory_quantity_cohort_id: row.inventory_quantity_cohort_id,
                            target_event_id: draft.context.targetEventId, quantity,
                            corrected_disposition: correctedDisposition, reason, effective_time: effectiveTime,
                            custody_location_id: custodyLocationId,
                          });
                          partialCorrectMutation.mutate(
                            { payload: payload as QualityPartialCorrectionCreate, farmId: row.received_at_farm_id, itemId: row.inventory_item_id },
                            {
                              onSuccess: () => draft.handleSuccess(generation),
                              onError: (err) => draft.handleError(asAppError(err), generation),
                            },
                          );
                        }}
                      />
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
        </>
      )}
    </div>
  );
}
