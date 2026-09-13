"use client";

import { useParams } from "next/navigation";
import { useState } from "react";

import { Breadcrumbs } from "@/components/Breadcrumbs";
import { ErrorState } from "@/components/ErrorState";
import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/components/ui/Button";
import type { InventoryPutawayCreate, NotPutAwayQueueEntryRead } from "@/lib/api/client";
import { useFrozenSubmission } from "@/lib/commands/frozenSubmission";
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

function PutawayRow({
  entry, bins, farmId,
}: {
  entry: NotPutAwayQueueEntryRead;
  bins: { id: string; label: string }[];
  farmId: string;
}) {
  const [expanded, setExpanded] = useState(false);
  const [binId, setBinId] = useState(bins[0]?.id ?? "");
  const [quantity, setQuantity] = useState("");
  const [effectiveTime, setEffectiveTime] = useState(() => nowLocalDateTime());
  const putawayMutation = useRecordInventoryPutaway();
  const command = useFrozenSubmission<InventoryPutawayCreate>();

  // PILOT-BLOCKER-008 A3: while the outcome is uncertain, every control
  // that could alter the payload must be disabled -- not just Cancel/reset.
  const isUncertain = command.outcome === "uncertain";
  const isSubmitting = command.outcome === "submitting";
  const fieldsDisabled = isSubmitting || isUncertain;
  const frozen = command.frozenPayload;
  const frozenBinLabel = frozen ? bins.find((b) => b.id === frozen.destination_location_id)?.label ?? frozen.destination_location_id : null;

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

  return (
    <li className="rounded-xl border border-wl-border bg-wl-surface-raised p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <p className="font-medium text-wl-text">{entry.item_name}</p>
          <p className="text-xs text-wl-text-tertiary">
            {entry.not_put_away_quantity} not put away
            {entry.manufacturer_lot_reference ? ` · Lot ${entry.manufacturer_lot_reference}` : ""}
            {` · Receipt ${entry.receipt_code}`}
          </p>
        </div>
        {!expanded && (
          <button
            type="button"
            className="rounded-md border border-wl-border-strong bg-wl-surface px-3 py-1.5 text-xs font-medium text-wl-text hover:bg-wl-surface-hover"
            onClick={() => setExpanded(true)}
            disabled={bins.length === 0}
            title={bins.length === 0 ? "No active Bins configured for this Farm yet" : undefined}
          >
            Put away
          </button>
        )}
      </div>

      {expanded && (
        <div className="mt-3 flex flex-col gap-3 rounded-lg border border-wl-border bg-wl-surface p-3">
          {/* PILOT-BLOCKER-008 A3 (CTO correction): while uncertain, render
              the unresolved command's DISPLAYED values from the frozen
              submitted payload itself, never from live form/query state --
              a background queue/tree refetch must never make the screen
              show values different from what Retry will actually resend. */}
          {isUncertain && frozen ? (
            <dl className="grid grid-cols-1 gap-2 text-xs text-wl-text-secondary sm:grid-cols-3">
              <div>
                <dt>Destination Bin</dt>
                <dd className="font-medium text-wl-text">{frozenBinLabel}</dd>
              </div>
              <div>
                <dt>Quantity</dt>
                <dd className="font-medium text-wl-text">{frozen.quantity}</dd>
              </div>
              <div>
                <dt>Effective time</dt>
                <dd className="font-medium text-wl-text">{new Date(frozen.effective_time).toLocaleString()}</dd>
              </div>
            </dl>
          ) : (
            <>
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
            </>
          )}

          {isUncertain && (
            <p className="rounded-md border border-amber-300 bg-amber-50 p-2 text-xs text-amber-900">
              Result not confirmed -- this putaway was submitted but the server&apos;s response was never received.
              Retry sends the exact same submitted values again; it is safe to press even if the original attempt
              actually went through.
            </p>
          )}
          {command.error && !isUncertain && (
            <p className="rounded-md border border-red-300 bg-red-50 p-2 text-xs text-red-800">
              {command.error.message}
            </p>
          )}

          <div className="flex gap-2">
            {isUncertain ? (
              <>
                <Button
                  type="button"
                  variant="primary"
                  disabled={isSubmitting}
                  onClick={() => {
                    const payload = command.retry();
                    if (!payload) return;
                    handleSettled({ farmId, payload });
                  }}
                >
                  {isSubmitting ? "Retrying…" : "Retry"}
                </Button>
                {/* Disabled for the whole uncertain state, not just while a
                    retry is in flight -- the frozen command must remain
                    recoverable until its outcome is actually resolved. */}
                <Button type="button" variant="secondary" disabled>
                  Cancel
                </Button>
              </>
            ) : (
              <>
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
              </>
            )}
          </div>
        </div>
      )}
    </li>
  );
}

/** STORE-INV-002B: the "Not put away" work queue -- everything with a
 * positive not-put-away quantity, company-wide, plus a compact inline
 * putaway action per row. Never a giant form -- destination Bin + quantity
 * + effective time only, no UUIDs shown. */
export default function StoreInventoryPutawayPage() {
  const { farmId } = useParams<{ farmId: string }>();
  const queueQuery = useNotPutAwayQueue();
  const treeQuery = useLocationsTree(farmId);

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
                <PutawayRow key={entry.inventory_quantity_cohort_id} entry={entry} bins={bins} farmId={farmId} />
              ))}
            </ul>
          )}
        </>
      )}
    </div>
  );
}
