"use client";

import { useParams } from "next/navigation";
import { useState } from "react";

import { Breadcrumbs } from "@/components/Breadcrumbs";
import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/components/ui/Button";
import { AppError } from "@/lib/errors/adapter";
import { activeBinsWithPaths } from "@/lib/locations/bins";
import {
  useCohortStorageBreakdown, useFarms, useInventoryItems, useItemExistenceProvenance, useItemFarmAvailability,
  useItemsExistenceSummary, useItemStorageBreakdown, useLocationsTree, useQualityWorkQueue,
  useRecordInventoryScrap, useRecordInventoryStorageTransfer, useUoms,
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
        <p className="rounded-md border border-wl-border bg-wl-flag-bg p-2 text-xs text-wl-flag-fg">{error.message}</p>
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

      {error && <p className="rounded-md border border-wl-border bg-wl-flag-bg p-2 text-xs text-wl-flag-fg">{error.message}</p>}

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

/** One cohort's own physical custody -- Not put away / per-Bin balances --
 * plus its Move stock / Scrap actions. Rendered as one flat row inside the
 * single selected-stock panel (PILOT-UX-003), never as a further nested
 * `<table>` inside a table row. */
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

  return (
    <div className="flex flex-col gap-1.5 rounded-lg border border-wl-border bg-wl-surface-raised p-2.5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="text-xs text-wl-text-secondary">
          {breakdownQuery.isLoading
            ? "Loading custody…"
            : breakdownQuery.isError
              ? "Custody detail unavailable — retry"
              : buckets.length === 0
                ? "Nothing recorded"
                : buckets.map((b) => `${b.label}: ${b.balance}`).join(" · ")}
        </span>
        {!breakdownQuery.isLoading && !breakdownQuery.isError && (
          <div className="flex gap-2">
            {binBuckets.length > 0 && !moving && (
              <button type="button" className="text-xs font-medium text-wl-brand hover:underline" onClick={() => setMoving(true)}>
                Move stock
              </button>
            )}
            {buckets.length > 0 && !scrapping && (
              <button type="button" className="text-xs font-medium text-wl-brand hover:underline" onClick={() => setScrapping(true)}>
                Scrap
              </button>
            )}
          </div>
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
      {scrapping && buckets.length > 0 && (
        <ScrapForm cohortId={cohortId} farmId={farmId} buckets={buckets} onDone={() => setScrapping(false)} />
      )}
    </div>
  );
}

/** The ONE selected-stock panel (PILOT-UX-003): everything about the item
 * currently selected in the Farm table -- Farm-scoped detail not already on
 * the row (Issued to operations, Not put away company-wide), then each
 * contributing cohort's own custody -- replacing the previous nested
 * table-inside-a-table-row structure with one flat panel. Cohort/bin detail
 * is fetched only for the selected item (`useItemExistenceProvenance`) and
 * only for its own cohorts (`useCohortStorageBreakdown`, one per cohort
 * actually shown here) -- never eagerly across the whole Inventory list. */
function SelectedStockPanel({
  itemId, itemName, farmId, uomCode, activeBins, farmNameById,
}: {
  itemId: string;
  itemName: string;
  farmId: string;
  uomCode: string | undefined;
  activeBins: { id: string; label: string }[];
  farmNameById: Map<string, string>;
}) {
  const availabilityQuery = useItemFarmAvailability(farmId, itemId);
  const notPutAwayQuery = useItemStorageBreakdown(itemId);
  const provenanceQuery = useItemExistenceProvenance(itemId);
  const fmt = (v: string | undefined) => (v === undefined ? "…" : uomCode ? `${v} ${uomCode}` : v);
  const rows = provenanceQuery.data ?? [];

  return (
    <div className="flex flex-col gap-3 rounded-xl border border-wl-border bg-wl-surface-sunken p-3">
      <h3 className="text-sm font-semibold text-wl-text">Selected: {itemName}</h3>
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-wl-text-secondary">
        <span>
          Issued to operations (this Farm):{" "}
          <span className="font-medium text-wl-text">
            {availabilityQuery.isError ? "Unavailable — retry" : fmt(availabilityQuery.data?.issued_to_operations_quantity)}
          </span>
        </span>
        <span>
          Not put away (company-wide):{" "}
          <span className="font-medium text-wl-text">
            {notPutAwayQuery.isError ? "Unavailable — retry" : fmt(notPutAwayQuery.data?.not_put_away_quantity)}
          </span>
        </span>
      </div>

      <div>
        <h4 className="mb-1.5 text-xs font-semibold text-wl-text-secondary">Contributing lots / cohorts</h4>
        {provenanceQuery.isLoading ? (
          <p className="text-sm text-wl-text-secondary">Loading…</p>
        ) : provenanceQuery.isError ? (
          <p className="text-sm text-wl-flag-fg">Could not load contributing cohorts — retry.</p>
        ) : rows.length === 0 ? (
          <p className="text-sm text-wl-text-secondary">No cohorts contribute to this total.</p>
        ) : (
          <ul className="flex flex-col gap-2">
            {rows.map((row) => (
              <li key={row.inventory_quantity_cohort_id} className="flex flex-col gap-1.5">
                <div className="flex flex-wrap items-baseline justify-between gap-2 text-xs">
                  <span className="text-wl-text">
                    Received at{" "}
                    <span className="font-medium">
                      {farmNameById.get(row.received_at_farm_id) ?? `Farm ${row.received_at_farm_id.slice(0, 8)}`}
                    </span>
                  </span>
                  <span className="font-medium tabular-nums text-wl-text">{row.balance}{uomCode ? ` ${uomCode}` : ""}</span>
                </div>
                <CohortCustodyRow cohortId={row.inventory_quantity_cohort_id} farmId={farmId} activeBins={activeBins} />
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

/** One row of the primary, Farm-scoped operational table -- Available to
 * issue / In store / Reserved, all from the one `useItemFarmAvailability`
 * read (never a separate call per column). */
function FarmScopedCells({ itemId, farmId, uomCode }: { itemId: string; farmId: string; uomCode: string | undefined }) {
  const availabilityQuery = useItemFarmAvailability(farmId, itemId);
  const fmt = (v: string | undefined) => (uomCode ? `${v} ${uomCode}` : v);
  if (availabilityQuery.isLoading) {
    return (
      <>
        <td className="p-3 text-wl-text-secondary">…</td>
        <td className="p-3 text-wl-text-secondary">…</td>
        <td className="p-3 text-wl-text-secondary">…</td>
      </>
    );
  }
  if (availabilityQuery.isError) {
    return (
      <>
        <td className="p-3 text-wl-flag-fg">Unavailable</td>
        <td className="p-3 text-wl-flag-fg">Unavailable</td>
        <td className="p-3 text-wl-flag-fg">Unavailable</td>
      </>
    );
  }
  return (
    <>
      <td className="p-3 tabular-nums text-wl-text">{fmt(availabilityQuery.data?.available_to_issue_quantity)}</td>
      <td className="p-3 tabular-nums text-wl-text">{fmt(availabilityQuery.data?.in_store_quantity)}</td>
      <td className="p-3 tabular-nums text-wl-text">{fmt(availabilityQuery.data?.reserved_quantity)}</td>
    </>
  );
}

/** STORE-INV-002A.2/002B: Farm-scoped operational stock -- Available to
 * issue / In store / Reserved / Attention, one row per active Item -- is the
 * default, primary view (PILOT-UX-003: routine daily operation defaults to
 * THIS Farm). Company-wide Existence/Usable totals are a distinct,
 * visually-secondary, collapsed-by-default section below, never mixed into
 * the same columns as this Farm's own custody. Selecting a row opens the one
 * `SelectedStockPanel` below the table with that Item's contributing
 * cohorts/Bins and Move/Scrap actions -- replacing the previous
 * table-nested-inside-a-table-row structure. */
export default function StoreInventoryInventoryPage() {
  const { farmId } = useParams<{ farmId: string }>();
  const itemsQuery = useInventoryItems({ status: "active" });
  const items = itemsQuery.data ?? [];
  const uomsQuery = useUoms();
  const uomsById = new Map((uomsQuery.data ?? []).map((u) => [u.id, u.code]));
  const [selectedItemId, setSelectedItemId] = useState<string | null>(null);
  const [companyWideOpen, setCompanyWideOpen] = useState(false);
  const treeQuery = useLocationsTree(farmId);
  const activeBins = activeBinsWithPaths(treeQuery.data ?? []);
  const farmsQuery = useFarms();
  const farmNameById = new Map((farmsQuery.data ?? []).map((f) => [f.id, f.name]));

  // ONE company-wide read for the whole page (never per-item/per-cohort) --
  // an Item has "Attention" here only if a queue row for one of its cohorts
  // was actually received at THIS Farm.
  const qualityQueueQuery = useQualityWorkQueue();
  const attentionItemIds = new Set(
    (qualityQueueQuery.data ?? [])
      .filter((row) => row.received_at_farm_id === farmId)
      .map((row) => row.inventory_item_id),
  );

  // Deferred until the operator actually opens the section -- never fetched
  // eagerly across every active Item just to render a collapsed summary.
  const companyWideSummary = useItemsExistenceSummary(items.map((i) => i.id), companyWideOpen);

  const selectedItem = items.find((i) => i.id === selectedItemId) ?? null;

  return (
    <div>
      <PageHeader
        title="Inventory"
        description="This Farm's stock, available to issue right now. Company-wide totals are a separate summary below."
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

      {itemsQuery.isLoading ? (
        <p className="text-sm text-wl-text-secondary">Loading…</p>
      ) : itemsQuery.isError ? (
        <p className="text-sm text-wl-flag-fg">Could not load Inventory Items — retry.</p>
      ) : items.length === 0 ? (
        <p className="text-sm text-wl-text">No active Inventory Items configured yet.</p>
      ) : (
        <div className="flex flex-col gap-4">
          <div className="overflow-x-auto rounded-xl border border-wl-border bg-wl-surface-raised">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-wl-border text-left text-wl-text-secondary">
                  <th className="p-3 font-medium">Item</th>
                  <th className="p-3 font-medium">Available to issue</th>
                  <th className="p-3 font-medium">In store</th>
                  <th className="p-3 font-medium">Reserved</th>
                  <th className="p-3 font-medium">Attention</th>
                  <th className="p-3 font-medium" />
                </tr>
              </thead>
              <tbody>
                {items.map((item) => {
                  const isSelected = selectedItemId === item.id;
                  const uomCode = uomsById.get(item.base_uom_id);
                  const hasAttention = attentionItemIds.has(item.id);
                  return (
                    <tr
                      key={item.id}
                      className={`cursor-pointer border-b border-wl-border last:border-0 hover:bg-wl-surface-hover ${isSelected ? "bg-wl-brand-subtle" : ""}`}
                      onClick={() => setSelectedItemId(isSelected ? null : item.id)}
                    >
                      <td className="p-3 font-medium text-wl-text">
                        {item.name}
                        {item.lot_tracking_required && (
                          <span className="ml-2 rounded bg-wl-surface-sunken px-1.5 py-0.5 text-[10px] uppercase text-wl-text-secondary">
                            lot-tracked
                          </span>
                        )}
                      </td>
                      <FarmScopedCells itemId={item.id} farmId={farmId} uomCode={uomCode} />
                      <td className="p-3">
                        {qualityQueueQuery.isLoading ? (
                          <span className="text-xs text-wl-text-secondary">…</span>
                        ) : qualityQueueQuery.isError ? (
                          <span className="text-xs text-wl-flag-fg">Unavailable</span>
                        ) : hasAttention ? (
                          <span className="inline-flex w-fit items-center rounded-full bg-wl-hold-bg px-2 py-0.5 text-xs font-medium text-wl-hold-fg">
                            Attention
                          </span>
                        ) : (
                          <span className="text-xs text-wl-text-secondary">—</span>
                        )}
                      </td>
                      <td className="p-3 text-right">
                        <button
                          type="button"
                          className="text-xs font-medium text-wl-brand hover:underline"
                          onClick={(e) => {
                            e.stopPropagation();
                            setSelectedItemId(isSelected ? null : item.id);
                          }}
                        >
                          {isSelected ? "Hide detail" : "Show detail"}
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {selectedItem && (
            <SelectedStockPanel
              itemId={selectedItem.id}
              itemName={selectedItem.name}
              farmId={farmId}
              uomCode={uomsById.get(selectedItem.base_uom_id)}
              activeBins={activeBins}
              farmNameById={farmNameById}
            />
          )}

          <div className="rounded-xl border border-wl-border bg-wl-surface-raised">
            <button
              type="button"
              className="w-full p-3 text-left text-sm font-medium text-wl-text-secondary hover:bg-wl-surface-hover"
              onClick={() => setCompanyWideOpen((open) => !open)}
              aria-expanded={companyWideOpen}
            >
              {companyWideOpen ? "▾" : "▸"} Company-wide totals (all Farms)
            </button>
            <div className="overflow-x-auto border-t border-wl-border" hidden={!companyWideOpen}>
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-wl-border text-left text-wl-text-secondary">
                    <th className="p-3 font-medium">Item</th>
                    <th className="p-3 font-medium">Exists</th>
                    <th className="p-3 font-medium">Usable</th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((item) => {
                    const row = companyWideSummary.byItemId[item.id];
                    const uomCode = uomsById.get(item.base_uom_id);
                    return (
                      <tr key={item.id} className="border-b border-wl-border last:border-0">
                        <td className="p-3 text-wl-text">{item.name}</td>
                        <td className="p-3 tabular-nums text-wl-text-secondary">
                          {!companyWideOpen || companyWideSummary.isLoading
                            ? "…"
                            : row?.existing !== undefined && row.existing !== null
                              ? `${row.existing} ${uomCode ?? ""}`.trim()
                              : "0"}
                        </td>
                        <td className="p-3 tabular-nums text-wl-text-secondary">
                          {!companyWideOpen || companyWideSummary.isLoading
                            ? "…"
                            : row?.usable !== undefined && row.usable !== null
                              ? `${row.usable} ${uomCode ?? ""}`.trim()
                              : "0"}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
