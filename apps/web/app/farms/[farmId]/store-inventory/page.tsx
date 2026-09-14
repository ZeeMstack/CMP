"use client";

import Link from "next/link";
import { useParams } from "next/navigation";

import { Breadcrumbs } from "@/components/Breadcrumbs";
import { PageHeader } from "@/components/PageHeader";
import { StoreSubNav } from "@/components/store-inventory/StoreSubNav";
import {
  useFarm, useFarms, useGoodsReceipts, useNotPutAwayQueue, useQualityWorkQueue, useUoms,
} from "@/lib/query/hooks";
import type { NotPutAwayQueueEntryRead, QualityWorkQueueRowRead } from "@/lib/api/client";

function primaryCtaClass(): string {
  return "inline-flex h-9 items-center gap-1.5 self-start rounded-[7px] bg-wl-brand px-4 text-sm font-medium text-wl-text-on-brand hover:bg-wl-brand-hover active:bg-wl-brand-pressed";
}

function secondaryCtaClass(): string {
  return "inline-flex h-9 items-center gap-1.5 self-start rounded-[7px] border border-wl-border-strong bg-wl-surface-raised px-4 text-sm font-medium text-wl-text hover:bg-wl-surface-hover";
}

function rowActionClass(): string {
  return "inline-flex h-7 items-center rounded-md border border-wl-border-strong bg-wl-surface px-2.5 text-xs font-medium text-wl-text hover:bg-wl-surface-hover";
}

/** Restrained inline warning for a source whose refresh failed but whose
 * previously loaded rows are still on screen -- never lets a stale/error
 * source get silently swapped for a bigger reassuring empty state (R1). */
function StaleNotice({ label, onRetry }: { label: string; onRetry: () => void }) {
  return (
    <p className="flex flex-wrap items-center gap-2 rounded-md border border-wl-border-strong bg-wl-flag-bg px-3 py-2 text-xs text-wl-flag-fg">
      Could not refresh {label} -- showing previously loaded data.
      <button type="button" className="font-medium underline" onClick={onRetry}>
        Retry
      </button>
    </p>
  );
}

/** A source that failed with no cached data at all -- distinct from
 * `StaleNotice`, which still has rows to show alongside the warning. */
function FailedNotice({ label, onRetry }: { label: string; onRetry: () => void }) {
  return (
    <p role="alert" className="flex flex-wrap items-center gap-2 rounded-md border border-wl-border-strong bg-wl-flag-bg px-3 py-2 text-xs text-wl-flag-fg">
      Could not load {label}.
      <button type="button" className="font-medium underline" onClick={onRetry}>
        Retry
      </button>
    </p>
  );
}

type ActionRow = {
  key: string;
  stage: "Quality" | "Putaway";
  reference: string;
  itemLabel: string;
  quantityLabel: string;
  statusLabel: string;
  // Receipt provenance ONLY (`received_at_farm_id` --
  // docs/domain/STORE_INVENTORY_MODEL.md §7: "provenance, never current
  // custody"). Never presented or reasoned about as this cohort's current
  // operational/custody Farm -- the read models available to this page do
  // not carry that fact.
  receivedAtFarmLabel: string;
  actionLabel: string;
  actionHref: string;
  sortTime: number;
};

function toQualityActionRow(
  row: QualityWorkQueueRowRead, uomCodeById: Map<string, string>, farmNameById: Map<string, string>,
): ActionRow {
  const uomCode = uomCodeById.get(row.base_uom_id);
  const rowFarmId = row.received_at_farm_id;
  return {
    key: `quality-${row.inventory_quantity_cohort_id}`,
    stage: "Quality",
    reference: row.receipt_code,
    itemLabel: row.manufacturer_lot_reference ? `${row.item_name} — Lot ${row.manufacturer_lot_reference}` : row.item_name,
    quantityLabel: uomCode ? `${row.balance} ${uomCode}` : String(row.balance),
    statusLabel: "Quarantined",
    receivedAtFarmLabel: farmNameById.get(rowFarmId) ?? `Farm ${rowFarmId.slice(0, 8)}`,
    actionLabel: "Review",
    // R6: this queue is company-wide, never scoped to the currently-viewed
    // Farm. `received_at_farm_id` is receipt provenance ONLY, never
    // authoritative current custody (docs/domain/STORE_INVENTORY_MODEL.md
    // §7) -- so this is NOT a custody-scoped route, it is a shell/context
    // choice: the app's URL shape requires a `/farms/{farmId}/...` prefix
    // for breadcrumbs, and the received-at Farm is the least-wrong Farm
    // context available, strictly better than defaulting to whichever Farm
    // the operator happens to be viewing right now (never construct
    // `/farms/FARM-1/...` for a receipt that says FARM-2). The Quality page
    // itself does not trust this route segment for anything -- it re-reads
    // its own company-wide, tenant-scoped queue and resolves `cohortId`
    // against that scoped result only; no operation is ever authorized from
    // the route Farm.
    actionHref: `/farms/${rowFarmId}/store-inventory/quality?cohortId=${row.inventory_quantity_cohort_id}`,
    sortTime: new Date(row.receipt_received_at).getTime(),
  };
}

function toPutawayActionRow(
  entry: NotPutAwayQueueEntryRead, uomCodeById: Map<string, string>, farmNameById: Map<string, string>,
): ActionRow {
  const uomCode = uomCodeById.get(entry.base_uom_id);
  const rowFarmId = entry.received_at_farm_id;
  return {
    key: `putaway-${entry.inventory_quantity_cohort_id}`,
    stage: "Putaway",
    reference: entry.receipt_code,
    itemLabel: entry.manufacturer_lot_reference ? `${entry.item_name} — Lot ${entry.manufacturer_lot_reference}` : entry.item_name,
    quantityLabel: uomCode ? `${entry.not_put_away_quantity} ${uomCode}` : String(entry.not_put_away_quantity),
    statusLabel: "Awaiting putaway",
    receivedAtFarmLabel: farmNameById.get(rowFarmId) ?? `Farm ${rowFarmId.slice(0, 8)}`,
    actionLabel: "Put away",
    // Same shell/context routing choice as Quality above -- `received_at_farm_id`
    // is provenance, not custody, and the Putaway page independently resolves
    // `cohortId` against its own scoped `useNotPutAwayQueue()` read.
    actionHref: `/farms/${rowFarmId}/store-inventory/putaway?cohortId=${entry.inventory_quantity_cohort_id}`,
    sortTime: new Date(entry.receipt_received_at).getTime(),
  };
}

/** STORE-INV-002A.2/002B, reworked under PILOT-UX-005 into the default
 * Store Operations workbench: context -> actions -> work queue -> recent
 * activity, replacing the four-card dashboard. Still an operational
 * summary, never a global readiness claim -- no invented readiness score,
 * no "available to issue" (docs/build-plans/
 * STORE_INV_002A2_QUALITY_OPERATIONAL_UX_BUILD_PLAN.md). Quality and
 * Putaway remain distinct workflow stages/routes -- this page surfaces them
 * as launched tasks, it does not re-implement their command logic.
 *
 * PILOT-BLOCKER-009 (R1): Quality, Putaway and Recent Receipts are three
 * independent reads. A failed read is NEVER converted to an empty array and
 * rendered as a safe "nothing needs action" state -- each source keeps its
 * own loading/success/empty/failed/stale distinction, and the global clean
 * empty state may only appear once Quality AND Putaway have both
 * successfully returned zero rows.
 *
 * PILOT-BLOCKER-009 (R6, residual known gap): both queues are intentionally
 * company-wide -- neither carries an authoritative current-custody Farm.
 * `received_at_farm_id` is receipt provenance only (docs/domain/
 * STORE_INVENTORY_MODEL.md §7) and is used here ONLY as (a) an honestly
 * labeled "Received at" display fact and (b) the least-wrong Farm segment
 * for this page's shell URLs -- never as proof of where a cohort currently
 * sits, and never to authorize anything. Precise current-Farm Store action
 * scope is not solved here; it needs custody/location-farm metadata the
 * read models do not yet expose. */
export default function StoreInventoryOverviewPage() {
  const { farmId } = useParams<{ farmId: string }>();
  const { data: farm } = useFarm(farmId);
  const receiptsQuery = useGoodsReceipts(farmId);
  const queueQuery = useQualityWorkQueue();
  const notPutAwayQuery = useNotPutAwayQueue();
  const uomsQuery = useUoms();
  const farmsQuery = useFarms();
  const uomCodeById = new Map((uomsQuery.data ?? []).map((u) => [u.id, u.code]));
  const farmNameById = new Map((farmsQuery.data ?? []).map((f) => [f.id, f.name]));

  // Each source's own cache presence, independent of whether its most
  // recent fetch/refetch succeeded -- react-query keeps `data` from the last
  // successful response even once a later refetch fails, which is exactly
  // what distinguishes "stale, refresh failed" from "no cache at all yet".
  const hasQualityData = queueQuery.data !== undefined;
  const hasPutawayData = notPutAwayQuery.data !== undefined;
  const hasReceiptsData = receiptsQuery.data !== undefined;

  const qualityFailedHard = queueQuery.isError && !hasQualityData;
  const qualityStale = queueQuery.isError && hasQualityData;
  const putawayFailedHard = notPutAwayQuery.isError && !hasPutawayData;
  const putawayStale = notPutAwayQuery.isError && hasPutawayData;

  const qualityPending = queueQuery.isLoading && !hasQualityData;
  const putawayPending = notPutAwayQuery.isLoading && !hasPutawayData;

  // A source's rows only ever contribute once it actually has data --
  // a failed-with-no-cache source contributes nothing, it never silently
  // becomes [].
  const awaitingDecision = hasQualityData
    ? (queueQuery.data ?? []).filter((row) => row.current_state === "RECEIVED_QUARANTINED")
    : [];
  const notPutAway = hasPutawayData ? (notPutAwayQuery.data ?? []) : [];

  const actionRows: ActionRow[] = [
    ...awaitingDecision.map((row) => toQualityActionRow(row, uomCodeById, farmNameById)),
    ...notPutAway.map((entry) => toPutawayActionRow(entry, uomCodeById, farmNameById)),
  ].sort((a, b) => b.sortTime - a.sortTime);

  // The clean "nothing needs action" claim requires BOTH sources to have
  // actually succeeded (not merely stale-but-cached) and both be genuinely
  // empty -- never shown merely because a failed source contributed zero
  // rows.
  const qualitySucceeded = hasQualityData && !queueQuery.isError;
  const putawaySucceeded = hasPutawayData && !notPutAwayQuery.isError;
  const showCleanEmpty = qualitySucceeded && putawaySucceeded && actionRows.length === 0;

  const recentReceipts = hasReceiptsData
    ? [...(receiptsQuery.data ?? [])].sort((a, b) => new Date(b.received_at).getTime() - new Date(a.received_at).getTime()).slice(0, 5)
    : [];
  const receiptsFailedHard = receiptsQuery.isError && !hasReceiptsData;
  const receiptsStale = receiptsQuery.isError && hasReceiptsData;
  const receiptsPending = receiptsQuery.isLoading && !hasReceiptsData;

  return (
    <div>
      <PageHeader
        title="Store Operations"
        description={farm ? `Store & Inventory for ${farm.name}` : "Store & Inventory"}
        breadcrumbs={
          <Breadcrumbs items={[{ label: "Home", href: `/farms/${farmId}` }, { label: "Store & Inventory" }]} />
        }
        actions={
          <>
            <Link href={`/farms/${farmId}/store-inventory/receive-goods`} className={primaryCtaClass()}>
              Receive Goods
            </Link>
            <Link href={`/farms/${farmId}/store-inventory/issue`} className={secondaryCtaClass()}>
              Issue Stock
            </Link>
            {/* R2: Quality has no permanent place in Store's simplified
                Operations/Inventory subnav (PILOT-UX-005) -- but it must
                always be reachable, not only when an Action Required row
                happens to exist. */}
            <Link href={`/farms/${farmId}/store-inventory/quality`} className={secondaryCtaClass()}>
              Manage Quality
            </Link>
          </>
        }
      />
      <StoreSubNav farmId={farmId} />

      <section className="flex flex-col gap-2">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h2 className="font-serif text-base font-semibold text-wl-text">Action Required</h2>
          <span className="text-xs text-wl-text-tertiary">Company-wide Quality &amp; Putaway work</span>
        </div>

        {qualityFailedHard && <FailedNotice label="the Quality queue" onRetry={() => queueQuery.refetch()} />}
        {putawayFailedHard && <FailedNotice label="the Putaway queue" onRetry={() => notPutAwayQuery.refetch()} />}
        {qualityStale && <StaleNotice label="the Quality queue" onRetry={() => queueQuery.refetch()} />}
        {putawayStale && <StaleNotice label="the Putaway queue" onRetry={() => notPutAwayQuery.refetch()} />}

        {qualityPending && putawayPending ? (
          <p className="text-sm text-wl-text-secondary">Loading…</p>
        ) : showCleanEmpty ? (
          <p className="rounded-xl border border-wl-border bg-wl-surface-raised p-4 text-sm text-wl-text">
            Nothing currently needs Quality or Putaway action.
          </p>
        ) : actionRows.length > 0 ? (
          <div className="overflow-x-auto rounded-xl border border-wl-border bg-wl-surface-raised">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-wl-border bg-wl-surface-sunken text-left text-xs font-medium text-wl-text-secondary">
                  <th className="p-3">Stage</th>
                  <th className="p-3">Reference</th>
                  <th className="p-3">Item / Lot</th>
                  <th className="p-3 text-right">Quantity</th>
                  <th className="p-3">Status</th>
                  {/* R6 correction: labeled truthfully as receipt provenance,
                      never "Current Farm"/"Custody Farm" -- this table has no
                      authoritative current-custody Farm to show. */}
                  <th className="p-3">Received at</th>
                  <th className="p-3">Action</th>
                </tr>
              </thead>
              <tbody>
                {actionRows.map((row) => (
                  <tr key={row.key} className="border-b border-wl-border last:border-0 hover:bg-wl-surface-hover">
                    <td className="p-3 align-top text-wl-text-secondary">{row.stage}</td>
                    <td className="p-3 align-top font-medium text-wl-text">{row.reference}</td>
                    <td className="p-3 align-top text-wl-text">{row.itemLabel}</td>
                    <td className="p-3 align-top text-right tabular-nums text-wl-text">{row.quantityLabel}</td>
                    <td className="p-3 align-top text-wl-text-secondary">{row.statusLabel}</td>
                    <td className="p-3 align-top text-wl-text-secondary">{row.receivedAtFarmLabel}</td>
                    <td className="p-3 align-top">
                      <Link href={row.actionHref} className={rowActionClass()}>
                        {row.actionLabel}
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
      </section>

      <section className="mt-5 flex flex-col gap-2">
        <h2 className="text-sm font-medium text-wl-text-secondary">Recent Goods Receipts</h2>
        {receiptsPending ? (
          <p className="text-sm text-wl-text-secondary">Loading…</p>
        ) : receiptsFailedHard ? (
          <FailedNotice label="Recent Receipts" onRetry={() => receiptsQuery.refetch()} />
        ) : (
          <>
            {receiptsStale && <StaleNotice label="Recent Receipts" onRetry={() => receiptsQuery.refetch()} />}
            {recentReceipts.length === 0 ? (
              !receiptsQuery.isError && <p className="text-sm text-wl-text-tertiary">No receipts recorded yet for this Farm.</p>
            ) : (
              <div className="overflow-x-auto rounded-xl border border-wl-border bg-wl-surface-raised">
                <table className="w-full text-sm">
                  <tbody>
                    {recentReceipts.map((r) => (
                      <tr key={r.id} className="border-b border-wl-border last:border-0">
                        <td className="p-2.5 font-medium text-wl-text">{r.code}</td>
                        <td className="p-2.5 text-right text-wl-text-tertiary">{new Date(r.received_at).toLocaleString()}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </>
        )}
      </section>
    </div>
  );
}
