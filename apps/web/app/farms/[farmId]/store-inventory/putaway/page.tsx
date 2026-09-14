"use client";

import { useParams, useSearchParams } from "next/navigation";
import { useState } from "react";

import { Breadcrumbs } from "@/components/Breadcrumbs";
import { ErrorState } from "@/components/ErrorState";
import { PageHeader } from "@/components/PageHeader";
import { StoreSubNav } from "@/components/store-inventory/StoreSubNav";
import { Button } from "@/components/ui/Button";
import type { InventoryPutawayCreate, NotPutAwayQueueEntryRead } from "@/lib/api/client";
import { useFrozenSubmission, type UseFrozenSubmissionResult } from "@/lib/commands/frozenSubmission";
import { nowLocalDateTime } from "@/lib/datetime";
import { AppError } from "@/lib/errors/adapter";
import { activeBinsWithPaths } from "@/lib/locations/bins";
import { useLocationsTree, useNotPutAwayQueue, useRecordInventoryPutaway } from "@/lib/query/hooks";

const inputClass =
  "min-h-10 w-full rounded-md border border-wl-border bg-wl-surface px-3 text-sm text-wl-text focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-wl-focus";
const labelClass = "block text-xs font-medium text-wl-text-secondary";

function asAppError(error: unknown): AppError {
  return error instanceof AppError ? error : new AppError("server_error", "Something went wrong. Please try again.");
}

/** PILOT-BLOCKER-010 sibling fix: `command`/`putawayMutation` are now owned
 * by the page, not this row -- passed as props. A queue refetch can drop
 * this exact `entry` out of `rows` at any time (the item got put away by
 * someone else, or simply left the company-wide "not put away" set), which
 * would unmount this row and, before this fix, destroy its frozen
 * `client_command_id`/payload along with it. See `PutawayRecoveryBanner` on
 * the page below, the stable surface that survives that unmount. */
function PutawayRow({
  entry, bins, farmId, initiallyExpanded, highlighted, command, putawayMutation, blockedByOtherCommand,
}: {
  entry: NotPutAwayQueueEntryRead;
  bins: { id: string; label: string }[];
  farmId: string;
  initiallyExpanded?: boolean;
  highlighted?: boolean;
  command: UseFrozenSubmissionResult<InventoryPutawayCreate>;
  putawayMutation: ReturnType<typeof useRecordInventoryPutaway>;
  blockedByOtherCommand: boolean;
}) {
  const [expanded, setExpanded] = useState(Boolean(initiallyExpanded));
  const [binId, setBinId] = useState(bins[0]?.id ?? "");
  const [quantity, setQuantity] = useState("");
  const [effectiveTime, setEffectiveTime] = useState(() => nowLocalDateTime());

  // PILOT-BLOCKER-008 A3: while the outcome is uncertain, every control
  // that could alter the payload must be disabled -- not just Cancel/reset.
  const isUncertain = command.outcome === "uncertain";
  const isSubmitting = command.outcome === "submitting";
  const fieldsDisabled = isSubmitting || isUncertain;
  const frozen = command.frozenPayload;
  // Re-derived from the frozen payload itself, not local `expanded` state --
  // `expanded` resets to `false` on remount (e.g. this row temporarily
  // dropped out of `rows` and came back), but the form must still reappear
  // here if this row is the one an unresolved command actually belongs to.
  const ownsUnresolvedCommand = frozen?.inventory_quantity_cohort_id === entry.inventory_quantity_cohort_id;
  const showForm = expanded || ownsUnresolvedCommand;

  function handleSettled(
    result: Parameters<typeof putawayMutation.mutate>[0],
  ) {
    putawayMutation.mutate(result, {
      onSuccess: () => {
        command.handleSuccess();
        setExpanded(false);
        setQuantity("");
      },
      onError: (err) => command.handleError(asAppError(err)),
    });
  }

  // PILOT-BLOCKER-010: once uncertain, this row no longer offers its own
  // Retry -- the page-level `PutawayRecoveryBanner` (always visible,
  // survives this row unmounting entirely) is the ONE canonical place to
  // retry, so there is never a moment with two different Retry buttons for
  // the same command.
  if (isUncertain && frozen) {
    return (
      <li
        id={`putaway-row-${entry.inventory_quantity_cohort_id}`}
        className={`rounded-xl border border-wl-border bg-wl-surface-raised p-4 ${highlighted ? "ring-2 ring-wl-brand" : ""}`}
      >
        <p className="font-medium text-wl-text">{entry.item_name}</p>
        <p className="mt-2 rounded-md border border-amber-300 bg-amber-50 p-2 text-xs text-amber-900">
          Result unknown for this Putaway. See the recovery notice at the top of the page to retry -- do not repeat
          this operation as a new transaction.
        </p>
      </li>
    );
  }

  return (
    <li
      id={`putaway-row-${entry.inventory_quantity_cohort_id}`}
      className={`rounded-xl border border-wl-border bg-wl-surface-raised p-4 ${highlighted ? "ring-2 ring-wl-brand" : ""}`}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <p className="font-medium text-wl-text">{entry.item_name}</p>
          <p className="text-xs text-wl-text-tertiary">
            {entry.not_put_away_quantity} not put away
            {entry.manufacturer_lot_reference ? ` · Lot ${entry.manufacturer_lot_reference}` : ""}
            {` · Receipt ${entry.receipt_code}`}
          </p>
        </div>
        {!showForm && (
          <button
            type="button"
            className="rounded-md border border-wl-border-strong bg-wl-surface px-3 py-1.5 text-xs font-medium text-wl-text hover:bg-wl-surface-hover disabled:cursor-not-allowed disabled:opacity-50"
            onClick={() => setExpanded(true)}
            disabled={bins.length === 0 || blockedByOtherCommand}
            title={
              bins.length === 0
                ? "No active Bins configured for this Farm yet"
                : blockedByOtherCommand
                  ? "Finish or retry the in-progress Putaway first"
                  : undefined
            }
          >
            Put away
          </button>
        )}
      </div>

      {showForm && (
        <div className="mt-3 flex flex-col gap-3 rounded-lg border border-wl-border bg-wl-surface p-3">
          <label className="flex flex-col gap-1">
            <span className={labelClass}>Destination Bin</span>
            <select
              className={inputClass} value={binId} onChange={(e) => setBinId(e.target.value)}
              disabled={fieldsDisabled}
            >
              {bins.map((b) => (
                <option key={b.id} value={b.id}>{b.label}</option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1">
            <span className={labelClass}>Quantity (of {entry.not_put_away_quantity} not put away)</span>
            <input
              className={inputClass}
              type="number"
              min="0"
              step="any"
              value={quantity}
              onChange={(e) => setQuantity(e.target.value)}
              disabled={fieldsDisabled}
            />
          </label>
          <label className="flex flex-col gap-1">
            <span className={labelClass}>Effective time</span>
            <input
              className={inputClass}
              type="datetime-local"
              value={effectiveTime}
              onChange={(e) => setEffectiveTime(e.target.value)}
              disabled={fieldsDisabled}
            />
          </label>

          {command.error && (
            <p className="rounded-md border border-red-300 bg-red-50 p-2 text-xs text-red-800">
              {command.error.message}
            </p>
          )}

          <div className="flex gap-2">
            <Button
              type="button"
              variant="primary"
              disabled={fieldsDisabled || !binId || !quantity || Number(quantity) <= 0}
              onClick={() => {
                const payload = command.submit((clientCommandId) => ({
                  client_command_id: clientCommandId,
                  inventory_quantity_cohort_id: entry.inventory_quantity_cohort_id,
                  destination_location_id: binId,
                  quantity,
                  effective_time: new Date(effectiveTime).toISOString(),
                  note: null,
                }));
                handleSettled({ farmId, payload });
              }}
            >
              {isSubmitting ? "Submitting…" : "Confirm putaway"}
            </Button>
            <Button
              type="button"
              variant="secondary"
              onClick={() => setExpanded(false)}
              disabled={fieldsDisabled}
            >
              Cancel
            </Button>
          </div>
        </div>
      )}
    </li>
  );
}

/** PILOT-BLOCKER-010: the stable, page-level recovery surface for a Putaway
 * whose result is unknown -- visible regardless of whether the originating
 * `PutawayRow` is still present in the current (possibly refetched) queue.
 * Bin labels come from `bins` (the page's own Farm-wide active Bin list,
 * always fetched independently of the queue), never from a per-row list
 * that could have disappeared along with the row. */
function PutawayRecoveryBanner({
  frozenPayload, bins, onRetry,
}: {
  frozenPayload: InventoryPutawayCreate;
  bins: { id: string; label: string }[];
  onRetry: () => void;
}) {
  const binLabel = bins.find((b) => b.id === frozenPayload.destination_location_id)?.label ?? frozenPayload.destination_location_id;
  return (
    <div
      role="alert"
      className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-amber-300 bg-amber-50 p-3 text-xs text-amber-900"
    >
      <div>
        <p className="font-semibold">Result unknown -- we couldn&apos;t confirm whether this Putaway was recorded.</p>
        <p>
          Destination {binLabel}, quantity {frozenPayload.quantity}. Do not repeat this operation as a new
          transaction.
        </p>
      </div>
      <Button type="button" variant="primary" onClick={onRetry}>
        Retry
      </Button>
    </div>
  );
}

/** STORE-INV-002B: the "Not put away" work queue -- everything with a
 * positive not-put-away quantity, company-wide, plus a compact inline
 * putaway action per row. Never a giant form -- destination Bin + quantity
 * + effective time only, no UUIDs shown. */
export default function StoreInventoryPutawayPage() {
  const { farmId } = useParams<{ farmId: string }>();
  const searchParams = useSearchParams();
  // PILOT-BLOCKER-009 R2: same row-specific continuation principle as
  // Quality -- the incoming cohort id is only ever resolved against this
  // page's own scoped queue read below, never trusted on its own, and it
  // never submits a Putaway automatically.
  const continuationCohortId = searchParams.get("cohortId");
  const queueQuery = useNotPutAwayQueue();
  const treeQuery = useLocationsTree(farmId);
  // PILOT-BLOCKER-010: owned HERE, above every disposable `PutawayRow`
  // instance, so an unresolved Putaway survives that row dropping out of a
  // refetched queue. See `PutawayRecoveryBanner` below.
  const putawayMutation = useRecordInventoryPutaway();
  const putawayCommand = useFrozenSubmission<InventoryPutawayCreate>();

  const rows = [...(queueQuery.data ?? [])].sort(
    (a, b) => new Date(b.receipt_received_at).getTime() - new Date(a.receipt_received_at).getTime(),
  );
  const bins = activeBinsWithPaths(treeQuery.data ?? []);
  // PILOT-BLOCKER-008 A7: a query FAILURE must never be presented as "zero
  // balance"/"no stock"/"nothing to put away"/"not configured" -- `data` is
  // retained across a failed react-query refetch, so its presence (even an
  // empty array/tree) distinguishes "stale, refresh failed" from "no cache
  // yet at all".
  const hasQueueData = queueQuery.data !== undefined;
  const hasTreeData = treeQuery.data !== undefined;

  const continuationEntry = continuationCohortId
    ? rows.find((entry) => entry.inventory_quantity_cohort_id === continuationCohortId)
    : undefined;
  const continuationMissing = Boolean(continuationCohortId) && hasQueueData && !queueQuery.isError && !continuationEntry;

  return (
    <div>
      <PageHeader
        title="Putaway"
        description="Place received material that has not yet been physically put away into a Bin."
        breadcrumbs={
          <Breadcrumbs
            items={[
              { label: "Home", href: `/farms/${farmId}` },
              { label: "Store & Inventory", href: `/farms/${farmId}/store-inventory` },
              { label: "Putaway" },
            ]}
          />
        }
      />
      <StoreSubNav farmId={farmId} />

      {putawayCommand.outcome === "uncertain" && putawayCommand.frozenPayload && (
        <PutawayRecoveryBanner
          frozenPayload={putawayCommand.frozenPayload}
          bins={bins}
          onRetry={() => {
            const payload = putawayCommand.retry();
            if (!payload) return;
            putawayMutation.mutate(
              { farmId, payload },
              {
                onSuccess: () => putawayCommand.handleSuccess(),
                onError: (err) => putawayCommand.handleError(err instanceof AppError ? err : new AppError("server_error", "Something went wrong. Please try again.")),
              },
            );
          }}
        />
      )}

      {continuationMissing && (
        <p className="mb-3 rounded-md border border-wl-border bg-wl-surface-sunken px-3 py-2 text-xs text-wl-text-secondary">
          That Putaway item is no longer in the current work queue.
        </p>
      )}

      {treeQuery.isError && !hasTreeData ? (
        <div className="mb-4">
          <ErrorState error={treeQuery.error} onRetry={() => treeQuery.refetch()} />
        </div>
      ) : treeQuery.isError ? (
        <p className="mb-4 flex flex-wrap items-center gap-2 rounded-md border border-wl-border-strong bg-wl-flag-bg px-3 py-2 text-xs text-wl-flag-fg">
          Could not refresh Bin locations -- showing the last known data.
          <button type="button" className="font-medium underline" onClick={() => treeQuery.refetch()}>
            Retry
          </button>
        </p>
      ) : (
        bins.length === 0 &&
        !treeQuery.isLoading && (
          <p className="mb-4 text-xs text-wl-text-tertiary">
            No active Bins are configured for this Farm yet. Set them up in Store & Inventory Setup first.
          </p>
        )
      )}

      {queueQuery.isLoading ? (
        <p className="text-sm text-wl-text-secondary">Loading…</p>
      ) : queueQuery.isError && !hasQueueData ? (
        <ErrorState error={queueQuery.error} onRetry={() => queueQuery.refetch()} />
      ) : (
        <>
          {queueQuery.isError && (
            <p className="mb-3 flex flex-wrap items-center gap-2 rounded-md border border-wl-border-strong bg-wl-flag-bg px-3 py-2 text-xs text-wl-flag-fg">
              Could not refresh the Putaway queue -- showing the last known data.
              <button type="button" className="font-medium underline" onClick={() => queueQuery.refetch()}>
                Retry
              </button>
            </p>
          )}
          {rows.length === 0 ? (
            !queueQuery.isError && <p className="text-sm text-wl-text">Nothing is currently awaiting putaway.</p>
          ) : (
            <ul className="flex flex-col gap-3">
              {rows.map((entry) => (
                <PutawayRow
                  key={entry.inventory_quantity_cohort_id}
                  entry={entry}
                  bins={bins}
                  farmId={farmId}
                  initiallyExpanded={entry.inventory_quantity_cohort_id === continuationCohortId}
                  highlighted={entry.inventory_quantity_cohort_id === continuationCohortId}
                  command={putawayCommand}
                  putawayMutation={putawayMutation}
                  blockedByOtherCommand={
                    putawayCommand.outcome !== "editing" &&
                    putawayCommand.frozenPayload?.inventory_quantity_cohort_id !== entry.inventory_quantity_cohort_id
                  }
                />
              ))}
            </ul>
          )}
        </>
      )}
    </div>
  );
}
