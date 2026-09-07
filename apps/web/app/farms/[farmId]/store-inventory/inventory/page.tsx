"use client";

import { useParams } from "next/navigation";
import { Fragment, useState } from "react";

import { Breadcrumbs } from "@/components/Breadcrumbs";
import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/components/ui/Button";
import { AppError } from "@/lib/errors/adapter";
import { activeBinsWithPaths } from "@/lib/locations/bins";
import {
  useCohortStorageBreakdown, useInventoryItems, useItemExistenceProvenance, useItemsExistenceSummary,
  useItemStorageBreakdown, useLocationsTree, useRecordInventoryStorageTransfer,
} from "@/lib/query/hooks";

const inputClass =
  "min-h-9 w-full rounded-md border border-wl-border bg-wl-surface px-2 text-xs text-wl-text focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-wl-focus";
const labelClass = "block text-[11px] font-medium text-wl-text-secondary";

function asAppError(error: unknown): AppError {
  return error instanceof AppError ? error : new AppError("server_error", "Something went wrong. Please try again.");
}

function nowLocalDateTime(): string {
  const now = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}T${pad(now.getHours())}:${pad(now.getMinutes())}`;
}

/** STORE-INV-002B: compact "Move stock" -- From Bin / To Bin / Quantity,
 * scoped to one cohort (a transfer moves one cohort's own custody between
 * two Bins in the same Farm; never a giant form, no UUIDs shown). */
function MoveStockForm({
  cohortId, farmId, fromBins, toBins, onDone,
}: {
  cohortId: string;
  farmId: string;
  fromBins: { id: string; label: string; balance: string }[];
  toBins: { id: string; label: string }[];
  onDone: () => void;
}) {
  const [sourceId, setSourceId] = useState(fromBins[0]?.id ?? "");
  const [destId, setDestId] = useState(toBins.find((b) => b.id !== fromBins[0]?.id)?.id ?? toBins[0]?.id ?? "");
  const [quantity, setQuantity] = useState("");
  const [effectiveTime, setEffectiveTime] = useState(() => nowLocalDateTime());
  const [error, setError] = useState<AppError | null>(null);
  const transferMutation = useRecordInventoryStorageTransfer();

  return (
    <div className="flex flex-col gap-2 rounded-lg border border-wl-border bg-wl-surface p-3">
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
        <label className="flex flex-col gap-1">
          <span className={labelClass}>From Bin</span>
          <select className={inputClass} value={sourceId} onChange={(e) => setSourceId(e.target.value)}>
            {fromBins.map((b) => (
              <option key={b.id} value={b.id}>{b.label} ({b.balance})</option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1">
          <span className={labelClass}>To Bin</span>
          <select className={inputClass} value={destId} onChange={(e) => setDestId(e.target.value)}>
            {toBins.map((b) => (
              <option key={b.id} value={b.id}>{b.label}</option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1">
          <span className={labelClass}>Quantity</span>
          <input
            className={inputClass}
            type="number"
            min="0"
            step="any"
            value={quantity}
            onChange={(e) => setQuantity(e.target.value)}
          />
        </label>
      </div>
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
          disabled={
            transferMutation.isPending || !sourceId || !destId || sourceId === destId ||
            !quantity || Number(quantity) <= 0
          }
          onClick={() => {
            setError(null);
            transferMutation.mutate(
              {
                farmId,
                payload: {
                  client_command_id: crypto.randomUUID(),
                  inventory_quantity_cohort_id: cohortId,
                  source_location_id: sourceId,
                  destination_location_id: destId,
                  quantity,
                  effective_time: new Date(effectiveTime).toISOString(),
                  note: null,
                },
              },
              { onSuccess: () => { setQuantity(""); onDone(); }, onError: (err) => setError(asAppError(err)) },
            );
          }}
        >
          {transferMutation.isPending ? "Submitting…" : "Confirm move"}
        </Button>
        <Button type="button" variant="secondary" onClick={onDone} disabled={transferMutation.isPending}>
          Cancel
        </Button>
      </div>
    </div>
  );
}

function CohortCustodyRow({
  cohortId, farmId, activeBins,
}: {
  cohortId: string;
  farmId: string;
  activeBins: { id: string; label: string }[];
}) {
  const breakdownQuery = useCohortStorageBreakdown(cohortId);
  const [moving, setMoving] = useState(false);
  const buckets = breakdownQuery.data?.buckets ?? [];
  const binBuckets = buckets.filter((b) => b.location_id !== null) as { location_id: string; label: string; balance: string }[];

  if (breakdownQuery.isLoading) return null;

  return (
    <div className="flex flex-col gap-1 border-t border-wl-border/60 px-2 py-1.5 text-[11px] text-wl-text-tertiary">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span>
          {buckets.length === 0
            ? "Nothing recorded"
            : buckets.map((b) => `${b.label}: ${b.balance}`).join(" · ")}
        </span>
        {binBuckets.length > 0 && !moving && (
          <button type="button" className="font-medium text-wl-brand hover:underline" onClick={() => setMoving(true)}>
            Move stock
          </button>
        )}
      </div>
      {moving && binBuckets.length > 0 && (
        <MoveStockForm
          cohortId={cohortId}
          farmId={farmId}
          fromBins={binBuckets.map((b) => ({ id: b.location_id, label: b.label, balance: b.balance }))}
          toBins={activeBins}
          onDone={() => setMoving(false)}
        />
      )}
    </div>
  );
}

function ProvenanceRows({ itemId, farmId, activeBins }: { itemId: string; farmId: string; activeBins: { id: string; label: string }[] }) {
  const provenanceQuery = useItemExistenceProvenance(itemId);
  const rows = provenanceQuery.data ?? [];
  if (provenanceQuery.isLoading) {
    return <p className="p-3 text-sm text-wl-text-secondary">Loading provenance…</p>;
  }
  if (rows.length === 0) {
    return <p className="p-3 text-sm text-wl-text-secondary">No cohorts contribute to this total.</p>;
  }
  return (
    <table className="w-full text-xs">
      <thead>
        <tr className="text-left text-wl-text-tertiary">
          <th className="p-2 font-medium">Cohort</th>
          <th className="p-2 font-medium">Balance</th>
          <th className="p-2 font-medium">Received at (Farm)</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <Fragment key={row.inventory_quantity_cohort_id}>
            <tr className="border-t border-wl-border">
              <td className="p-2 font-mono text-wl-text-tertiary">{row.inventory_quantity_cohort_id.slice(0, 8)}</td>
              <td className="p-2 text-wl-text">{row.balance}</td>
              <td className="p-2 text-wl-text-tertiary">Received at Farm {row.received_at_farm_id.slice(0, 8)}</td>
            </tr>
            <tr>
              <td colSpan={3} className="p-0">
                <CohortCustodyRow cohortId={row.inventory_quantity_cohort_id} farmId={farmId} activeBins={activeBins} />
              </td>
            </tr>
          </Fragment>
        ))}
      </tbody>
    </table>
  );
}

/** STORE-INV-002A.2/002B: company-wide existence + usable quantity, by
 * item, plus (as of 002B) each contributing cohort's own physical custody
 * breakdown -- "Not put away" and per-Bin balances -- and a compact "Move
 * stock" action. Never labels usable as "available" -- Reservation does
 * not exist yet. Custody is Farm-scoped (a Bin belongs to one Farm); the
 * Farm selector changes which Bins "Move stock" can target, never the
 * company-wide existence/usable totals themselves (docs/domain/
 * STORE_INVENTORY_MODEL.md §13/§18). */
export default function StoreInventoryInventoryPage() {
  const { farmId } = useParams<{ farmId: string }>();
  const itemsQuery = useInventoryItems({ status: "active" });
  const items = itemsQuery.data ?? [];
  const summary = useItemsExistenceSummary(items.map((i) => i.id));
  const [expandedItemId, setExpandedItemId] = useState<string | null>(null);
  const treeQuery = useLocationsTree(farmId);
  const activeBins = activeBinsWithPaths(treeQuery.data ?? []);

  return (
    <div>
      <PageHeader
        title="Inventory"
        description="Company-wide existence and usable quantity, shared across every Farm in this tenant."
        breadcrumbs={
          <Breadcrumbs
            items={[
              { label: "Home", href: `/farms/${farmId}` },
              { label: "Store & Inventory", href: `/farms/${farmId}/store-inventory` },
              { label: "Inventory" },
            ]}
          />
        }
      />
      <p className="mb-4 text-xs text-wl-text-tertiary">
        Selecting a different Farm changes which Bins &ldquo;Move stock&rdquo; can target, not the totals below.
      </p>

      {itemsQuery.isLoading ? (
        <p className="text-sm text-wl-text-secondary">Loading…</p>
      ) : items.length === 0 ? (
        <p className="text-sm text-wl-text">No active Inventory Items configured yet.</p>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-wl-border bg-wl-surface-raised">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-wl-border text-left text-wl-text-tertiary">
                <th className="p-3 font-medium">Item</th>
                <th className="p-3 font-medium">Exists</th>
                <th className="p-3 font-medium">Usable</th>
                <th className="p-3 font-medium">Not put away</th>
                <th className="p-3 font-medium" />
              </tr>
            </thead>
            <tbody>
              {items.map((item) => {
                const row = summary.byItemId[item.id];
                const isExpanded = expandedItemId === item.id;
                return (
                  <Fragment key={item.id}>
                    <tr className="border-b border-wl-border last:border-0">
                      <td className="p-3 font-medium text-wl-text">
                        {item.name}
                        {item.lot_tracking_required && (
                          <span className="ml-2 rounded bg-wl-surface px-1.5 py-0.5 text-[10px] uppercase text-wl-text-tertiary">
                            lot-tracked
                          </span>
                        )}
                      </td>
                      <td className="p-3 text-wl-text">{summary.isLoading ? "…" : row?.existing ?? "0"}</td>
                      <td className="p-3 text-wl-text">{summary.isLoading ? "…" : row?.usable ?? "0"}</td>
                      <td className="p-3 text-wl-text">
                        <NotPutAwayCell itemId={item.id} />
                      </td>
                      <td className="p-3 text-right">
                        <button
                          type="button"
                          className="text-xs font-medium text-wl-brand hover:underline"
                          onClick={() => setExpandedItemId(isExpanded ? null : item.id)}
                        >
                          {isExpanded ? "Hide detail" : "Show detail"}
                        </button>
                      </td>
                    </tr>
                    {isExpanded && (
                      <tr className="border-b border-wl-border bg-wl-surface last:border-0">
                        <td colSpan={5} className="p-0">
                          <ProvenanceRows itemId={item.id} farmId={farmId} activeBins={activeBins} />
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
  );
}

function NotPutAwayCell({ itemId }: { itemId: string }) {
  const breakdownQuery = useItemStorageBreakdown(itemId);
  if (breakdownQuery.isLoading) return <>…</>;
  return <>{breakdownQuery.data?.not_put_away_quantity ?? "0"}</>;
}
