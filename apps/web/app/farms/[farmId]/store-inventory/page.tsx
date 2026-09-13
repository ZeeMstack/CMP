"use client";

import Link from "next/link";
import { useParams } from "next/navigation";

import { Breadcrumbs } from "@/components/Breadcrumbs";
import { PageHeader } from "@/components/PageHeader";
import { StoreSubNav } from "@/components/store-inventory/StoreSubNav";
import {
  useFarm, useGoodsReceipts, useNotPutAwayQueue, useQualityWorkQueue, useUoms,
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

type ActionRow = {
  key: string;
  stage: "Quality" | "Putaway";
  reference: string;
  itemLabel: string;
  quantityLabel: string;
  statusLabel: string;
  actionLabel: string;
  actionHref: string;
  sortTime: number;
};

function toQualityActionRow(row: QualityWorkQueueRowRead, farmId: string, uomCodeById: Map<string, string>): ActionRow {
  const uomCode = uomCodeById.get(row.base_uom_id);
  return {
    key: `quality-${row.inventory_quantity_cohort_id}`,
    stage: "Quality",
    reference: row.receipt_code,
    itemLabel: row.manufacturer_lot_reference ? `${row.item_name} — Lot ${row.manufacturer_lot_reference}` : row.item_name,
    quantityLabel: uomCode ? `${row.balance} ${uomCode}` : String(row.balance),
    statusLabel: "Quarantined",
    actionLabel: "Review",
    actionHref: `/farms/${farmId}/store-inventory/quality`,
    sortTime: new Date(row.receipt_received_at).getTime(),
  };
}

function toPutawayActionRow(entry: NotPutAwayQueueEntryRead, farmId: string, uomCodeById: Map<string, string>): ActionRow {
  const uomCode = uomCodeById.get(entry.base_uom_id);
  return {
    key: `putaway-${entry.inventory_quantity_cohort_id}`,
    stage: "Putaway",
    reference: entry.receipt_code,
    itemLabel: entry.manufacturer_lot_reference ? `${entry.item_name} — Lot ${entry.manufacturer_lot_reference}` : entry.item_name,
    quantityLabel: uomCode ? `${entry.not_put_away_quantity} ${uomCode}` : String(entry.not_put_away_quantity),
    statusLabel: "Awaiting putaway",
    actionLabel: "Put away",
    actionHref: `/farms/${farmId}/store-inventory/putaway`,
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
 * as launched tasks, it does not re-implement their command logic. */
export default function StoreInventoryOverviewPage() {
  const { farmId } = useParams<{ farmId: string }>();
  const { data: farm } = useFarm(farmId);
  const receiptsQuery = useGoodsReceipts(farmId);
  const queueQuery = useQualityWorkQueue();
  const notPutAwayQuery = useNotPutAwayQueue();
  const uomsQuery = useUoms();
  const uomCodeById = new Map((uomsQuery.data ?? []).map((u) => [u.id, u.code]));

  const recentReceipts = [...(receiptsQuery.data ?? [])]
    .sort((a, b) => new Date(b.received_at).getTime() - new Date(a.received_at).getTime())
    .slice(0, 5);

  const awaitingDecision = (queueQuery.data ?? []).filter((row) => row.current_state === "RECEIVED_QUARANTINED");
  const notPutAway = notPutAwayQuery.data ?? [];

  const actionRows: ActionRow[] = [
    ...awaitingDecision.map((row) => toQualityActionRow(row, farmId, uomCodeById)),
    ...notPutAway.map((entry) => toPutawayActionRow(entry, farmId, uomCodeById)),
  ].sort((a, b) => b.sortTime - a.sortTime);

  const isLoadingQueues = queueQuery.isLoading || notPutAwayQuery.isLoading;

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
          </>
        }
      />
      <StoreSubNav farmId={farmId} />

      <section className="flex flex-col gap-2">
        <h2 className="font-serif text-base font-semibold text-wl-text">Action Required</h2>
        {isLoadingQueues ? (
          <p className="text-sm text-wl-text-secondary">Loading…</p>
        ) : actionRows.length === 0 ? (
          <p className="rounded-xl border border-wl-border bg-wl-surface-raised p-4 text-sm text-wl-text">
            Nothing currently needs Quality or Putaway action.
          </p>
        ) : (
          <div className="overflow-x-auto rounded-xl border border-wl-border bg-wl-surface-raised">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-wl-border bg-wl-surface-sunken text-left text-xs font-medium text-wl-text-secondary">
                  <th className="p-3">Stage</th>
                  <th className="p-3">Reference</th>
                  <th className="p-3">Item / Lot</th>
                  <th className="p-3 text-right">Quantity</th>
                  <th className="p-3">Status</th>
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
        )}
      </section>

      <section className="mt-5 flex flex-col gap-2">
        <h2 className="text-sm font-medium text-wl-text-secondary">Recent Goods Receipts</h2>
        {receiptsQuery.isLoading ? (
          <p className="text-sm text-wl-text-secondary">Loading…</p>
        ) : recentReceipts.length === 0 ? (
          <p className="text-sm text-wl-text-tertiary">No receipts recorded yet for this Farm.</p>
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
      </section>
    </div>
  );
}
