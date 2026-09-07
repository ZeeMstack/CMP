"use client";

import { useParams } from "next/navigation";
import { useState } from "react";

import { Breadcrumbs } from "@/components/Breadcrumbs";
import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/components/ui/Button";
import type { NotPutAwayQueueEntryRead } from "@/lib/api/client";
import { AppError } from "@/lib/errors/adapter";
import { activeBinsWithPaths } from "@/lib/locations/bins";
import { useLocationsTree, useNotPutAwayQueue, useRecordInventoryPutaway } from "@/lib/query/hooks";

const inputClass =
  "min-h-10 w-full rounded-md border border-wl-border bg-wl-surface px-3 text-sm text-wl-text focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-wl-focus";
const labelClass = "block text-xs font-medium text-wl-text-secondary";

function asAppError(error: unknown): AppError {
  return error instanceof AppError ? error : new AppError("server_error", "Something went wrong. Please try again.");
}

function nowLocalDateTime(): string {
  const now = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}T${pad(now.getHours())}:${pad(now.getMinutes())}`;
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
  const [error, setError] = useState<AppError | null>(null);
  const putawayMutation = useRecordInventoryPutaway();

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
          <label className="flex flex-col gap-1">
            <span className={labelClass}>Destination Bin</span>
            <select className={inputClass} value={binId} onChange={(e) => setBinId(e.target.value)}>
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
            />
          </label>
          <label className="flex flex-col gap-1">
            <span className={labelClass}>Effective time</span>
            <input
              className={inputClass}
              type="datetime-local"
              value={effectiveTime}
              onChange={(e) => setEffectiveTime(e.target.value)}
            />
          </label>

          {error && (
            <p className="rounded-md border border-red-300 bg-red-50 p-2 text-xs text-red-800">{error.message}</p>
          )}

          <div className="flex gap-2">
            <Button
              type="button"
              variant="primary"
              disabled={putawayMutation.isPending || !binId || !quantity || Number(quantity) <= 0}
              onClick={() => {
                setError(null);
                putawayMutation.mutate(
                  {
                    farmId,
                    payload: {
                      client_command_id: crypto.randomUUID(),
                      inventory_quantity_cohort_id: entry.inventory_quantity_cohort_id,
                      destination_location_id: binId,
                      quantity,
                      effective_time: new Date(effectiveTime).toISOString(),
                      note: null,
                    },
                  },
                  {
                    onSuccess: () => {
                      setExpanded(false);
                      setQuantity("");
                    },
                    onError: (err) => setError(asAppError(err)),
                  },
                );
              }}
            >
              {putawayMutation.isPending ? "Submitting…" : "Confirm putaway"}
            </Button>
            <Button
              type="button"
              variant="secondary"
              onClick={() => {
                setExpanded(false);
                setError(null);
              }}
              disabled={putawayMutation.isPending}
            >
              Cancel
            </Button>
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

      {bins.length === 0 && !treeQuery.isLoading && (
        <p className="mb-4 text-xs text-wl-text-tertiary">
          No active Bins are configured for this Farm yet. Set them up in Store & Inventory Setup first.
        </p>
      )}

      {queueQuery.isLoading ? (
        <p className="text-sm text-wl-text-secondary">Loading…</p>
      ) : rows.length === 0 ? (
        <p className="text-sm text-wl-text">Nothing is currently awaiting putaway.</p>
      ) : (
        <ul className="flex flex-col gap-3">
          {rows.map((entry) => (
            <PutawayRow key={entry.inventory_quantity_cohort_id} entry={entry} bins={bins} farmId={farmId} />
          ))}
        </ul>
      )}
    </div>
  );
}
