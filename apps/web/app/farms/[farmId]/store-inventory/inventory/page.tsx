"use client";

import { useParams } from "next/navigation";
import { Fragment, useState } from "react";

import { Breadcrumbs } from "@/components/Breadcrumbs";
import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/components/ui/Button";
import { AppError } from "@/lib/errors/adapter";
import { activeBinsWithPaths } from "@/lib/locations/bins";
import {
  useCohortStorageBreakdown, useInventoryItems, useItemExistenceProvenance, useItemFarmAvailability,
  useItemsExistenceSummary, useItemStorageBreakdown, useLocationsTree, useRecordInventoryScrap,
  useRecordInventoryStorageTransfer, useUoms,
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

/** STORE-INV-004: compact "Record scrap" -- Source (Not put away / a
 * specific Bin) / Qty / Reason, scoped to one cohort. Mirrors
 * `MoveStockForm`'s own compact shape exactly. */
function ScrapForm({
  cohortId, farmId, buckets, onDone,
}: {
  cohortId: string;
  farmId: string;
  buckets: { location_id: string | null; label: string; balance: string }[];
  onDone: () => void;
}) {
  const [sourceKey, setSourceKey] = useState(buckets[0] ? (buckets[0].location_id ?? "not_put_away") : "");
  const [quantity, setQuantity] = useState("");
  const [reason, setReason] = useState("");
  const [error, setError] = useState<AppError | null>(null);
  const scrapMutation = useRecordInventoryScrap();

  return (
    <div className="flex flex-col gap-2 rounded-lg border border-wl-border bg-wl-surface p-3">
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
        <label className="flex flex-col gap-1">
          <span className={labelClass}>Source</span>
          <select className={inputClass} value={sourceKey} onChange={(e) => setSourceKey(e.target.value)}>
            {buckets.map((b) => (
              <option key={b.location_id ?? "not_put_away"} value={b.location_id ?? "not_put_away"}>
                {b.label} ({b.balance})
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1">
          <span className={labelClass}>Quantity</span>
          <input
            className={inputClass} type="number" min="0" step="any" value={quantity}
            onChange={(e) => setQuantity(e.target.value)}
          />
        </label>
        <label className="flex flex-col gap-1">
          <span className={labelClass}>Reason</span>
          <input className={inputClass} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. damaged packaging" />
        </label>
      </div>

      {error && <p className="rounded-md border border-red-300 bg-red-50 p-2 text-xs text-red-800">{error.message}</p>}

      <div className="flex gap-2">
        <Button
          type="button" variant="primary"
          disabled={scrapMutation.isPending || !sourceKey || !quantity || Number(quantity) <= 0 || !reason.trim()}
          onClick={() => {
            setError(null);
            const isNotPutAway = sourceKey === "not_put_away";
            scrapMutation.mutate(
              {
                farmId,
                payload: {
                  client_command_id: crypto.randomUUID(),
                  source_kind: isNotPutAway ? "not_put_away" : "store_bin",
                  inventory_quantity_cohort_id: cohortId,
                  source_location_id: isNotPutAway ? null : sourceKey,
                  quantity, reason: reason.trim(), effective_time: new Date().toISOString(),
                },
              },
              { onSuccess: () => { setQuantity(""); setReason(""); onDone(); }, onError: (err) => setError(asAppError(err)) },
            );
          }}
        >
          {scrapMutation.isPending ? "Recording…" : "Record scrap"}
        </Button>
        <Button type="button" variant="secondary" onClick={onDone} disabled={scrapMutation.isPending}>
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
  const [scrapping, setScrapping] = useState(false);
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
        <div className="flex gap-2">
          {binBuckets.length > 0 && !moving && (
            <button type="button" className="font-medium text-wl-brand hover:underline" onClick={() => setMoving(true)}>
              Move stock
            </button>
          )}
          {buckets.length > 0 && !scrapping && (
            <button type="button" className="font-medium text-wl-brand hover:underline" onClick={() => setScrapping(true)}>
              Scrap
            </button>
          )}
        </div>
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
      {scrapping && buckets.length > 0 && (
        <ScrapForm cohortId={cohortId} farmId={farmId} buckets={buckets} onDone={() => setScrapping(false)} />
      )}
    </div>
  );
}

function FarmAvailabilitySummary({ itemId, farmId, uomCode }: { itemId: string; farmId: string; uomCode: string | undefined }) {
  const availabilityQuery = useItemFarmAvailability(farmId, itemId);
  const notPutAwayQuery = useItemStorageBreakdown(itemId);
  const fmt = (v: string | undefined) => (v === undefined ? "…" : uomCode ? `${v} ${uomCode}` : v);

  return (
    <div className="flex flex-wrap gap-x-4 gap-y-1 border-b border-wl-border/60 px-3 py-2 text-[11px] text-wl-text-secondary">
      <span>In Store (this Farm): <span className="font-medium text-wl-text">{fmt(availabilityQuery.data?.in_store_quantity)}</span></span>
      <span>Reserved (this Farm): <span className="font-medium text-wl-text">{fmt(availabilityQuery.data?.reserved_quantity)}</span></span>
      <span>Issued to operations (this Farm): <span className="font-medium text-wl-text">{fmt(availabilityQuery.data?.issued_to_operations_quantity)}</span></span>
      <span>Not put away (company-wide): <span className="font-medium text-wl-text">{fmt(notPutAwayQuery.data?.not_put_away_quantity)}</span></span>
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
  const uomsQuery = useUoms();
  const uomsById = new Map((uomsQuery.data ?? []).map((u) => [u.id, u.code]));
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
        Exists/Usable are company-wide. Available to issue, and the expanded detail&apos;s In Store/Reserved/Issued
        to operations, are scoped to the selected Farm.
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
                <th className="p-3 font-medium">Available to issue</th>
                <th className="p-3 font-medium" />
              </tr>
            </thead>
            <tbody>
              {items.map((item) => {
                const row = summary.byItemId[item.id];
                const isExpanded = expandedItemId === item.id;
                const uomCode = uomsById.get(item.base_uom_id);
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
                      <td className="p-3 text-wl-text">
                        {summary.isLoading ? "…" : row?.existing !== undefined ? `${row.existing} ${uomCode ?? ""}`.trim() : "0"}
                      </td>
                      <td className="p-3 text-wl-text">
                        {summary.isLoading ? "…" : row?.usable !== undefined ? `${row.usable} ${uomCode ?? ""}`.trim() : "0"}
                      </td>
                      <td className="p-3 text-wl-text">
                        <AvailableToIssueCell itemId={item.id} farmId={farmId} uomCode={uomCode} />
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
                          <FarmAvailabilitySummary itemId={item.id} farmId={farmId} uomCode={uomCode} />
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

function AvailableToIssueCell({ itemId, farmId, uomCode }: { itemId: string; farmId: string; uomCode: string | undefined }) {
  const availabilityQuery = useItemFarmAvailability(farmId, itemId);
  if (availabilityQuery.isLoading) return <>…</>;
  const value = availabilityQuery.data?.available_to_issue_quantity ?? "0";
  return <>{uomCode ? `${value} ${uomCode}` : value}</>;
}
