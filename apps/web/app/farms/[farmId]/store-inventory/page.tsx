"use client";

import Link from "next/link";
import { useParams } from "next/navigation";

import { Breadcrumbs } from "@/components/Breadcrumbs";
import { PageHeader } from "@/components/PageHeader";
import { useFarm, useGoodsReceipts, useNotPutAwayQueue, useQualityWorkQueue } from "@/lib/query/hooks";

function primaryCtaClass(): string {
  return "inline-flex h-9 items-center gap-1.5 self-start rounded-[7px] bg-wl-brand px-4 text-sm font-medium text-wl-text-on-brand hover:bg-wl-brand-hover active:bg-wl-brand-pressed";
}

function secondaryCtaClass(): string {
  return "inline-flex h-9 items-center gap-1.5 self-start rounded-[7px] border border-wl-border-strong bg-wl-surface-raised px-4 text-sm font-medium text-wl-text hover:bg-wl-surface-hover";
}

/** STORE-INV-002A.2/002B: an operational summary, never a global readiness
 * claim -- no invented readiness score, no "available to issue" (docs/
 * build-plans/STORE_INV_002A2_QUALITY_OPERATIONAL_UX_BUILD_PLAN.md). As of
 * 002B, a factual "awaiting putaway" count is included -- still no current
 * Store/Bin location claim beyond that one company-wide number. */
export default function StoreInventoryOverviewPage() {
  const { farmId } = useParams<{ farmId: string }>();
  const { data: farm } = useFarm(farmId);
  const receiptsQuery = useGoodsReceipts(farmId);
  const queueQuery = useQualityWorkQueue();
  const notPutAwayQuery = useNotPutAwayQueue();

  const recentReceipts = [...(receiptsQuery.data ?? [])]
    .sort((a, b) => new Date(b.received_at).getTime() - new Date(a.received_at).getTime())
    .slice(0, 5);

  const queue = queueQuery.data ?? [];
  const awaitingDecision = queue.filter((row) => row.current_state === "RECEIVED_QUARANTINED");
  const recentDecisions = [...queue]
    .filter((row) => row.current_state !== "RECEIVED_QUARANTINED" && row.last_effective_time)
    .sort((a, b) => new Date(b.last_effective_time as string).getTime() - new Date(a.last_effective_time as string).getTime())
    .slice(0, 5);

  return (
    <div>
      <PageHeader
        title="Store & Inventory"
        description={farm ? `Overview for ${farm.name}` : undefined}
        breadcrumbs={
          <Breadcrumbs items={[{ label: "Home", href: `/farms/${farmId}` }, { label: "Store & Inventory" }]} />
        }
      />

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <section className="flex flex-col gap-2 rounded-xl border border-wl-border bg-wl-surface-raised p-4">
          <h2 className="font-serif text-base font-semibold text-wl-text">Recent Goods Receipts</h2>
          {receiptsQuery.isLoading ? (
            <p className="text-sm text-wl-text-secondary">Loading…</p>
          ) : recentReceipts.length === 0 ? (
            <>
              <p className="text-sm text-wl-text">No receipts recorded yet for this Farm.</p>
              <Link href={`/farms/${farmId}/store-inventory/receive-goods`} className={primaryCtaClass()}>
                Receive Goods
              </Link>
            </>
          ) : (
            <>
              <ul className="flex flex-col gap-2 text-sm">
                {recentReceipts.map((r) => (
                  <li key={r.id} className="flex items-center justify-between border-b border-wl-border pb-2 last:border-0">
                    <span className="font-medium text-wl-text">{r.code}</span>
                    <span className="text-wl-text-tertiary">{new Date(r.received_at).toLocaleString()}</span>
                  </li>
                ))}
              </ul>
              <Link href={`/farms/${farmId}/store-inventory/receive-goods`} className={secondaryCtaClass()}>
                Receive Goods
              </Link>
            </>
          )}
        </section>

        <section className="flex flex-col gap-2 rounded-xl border border-wl-border bg-wl-surface-raised p-4">
          <h2 className="font-serif text-base font-semibold text-wl-text">Awaiting Quality Action</h2>
          {queueQuery.isLoading ? (
            <p className="text-sm text-wl-text-secondary">Loading…</p>
          ) : awaitingDecision.length === 0 ? (
            <p className="text-sm text-wl-text">Nothing is currently quarantined awaiting a decision.</p>
          ) : (
            <>
              <p className="text-sm text-wl-text">
                {awaitingDecision.length} {awaitingDecision.length === 1 ? "quantity" : "quantities"} awaiting a
                Quality decision, across {new Set(awaitingDecision.map((r) => r.inventory_item_id)).size}{" "}
                item(s).
              </p>
              <Link href={`/farms/${farmId}/store-inventory/quality`} className={primaryCtaClass()}>
                Go to Quality
              </Link>
            </>
          )}
        </section>

        <section className="flex flex-col gap-2 rounded-xl border border-wl-border bg-wl-surface-raised p-4">
          <h2 className="font-serif text-base font-semibold text-wl-text">Awaiting Putaway</h2>
          {notPutAwayQuery.isLoading ? (
            <p className="text-sm text-wl-text-secondary">Loading…</p>
          ) : (notPutAwayQuery.data ?? []).length === 0 ? (
            <p className="text-sm text-wl-text">Nothing is currently awaiting putaway.</p>
          ) : (
            <>
              <p className="text-sm text-wl-text">
                {(notPutAwayQuery.data ?? []).length}{" "}
                {(notPutAwayQuery.data ?? []).length === 1 ? "receipt line" : "receipt lines"} not yet put away,
                across {new Set((notPutAwayQuery.data ?? []).map((r) => r.inventory_item_id)).size} item(s).
              </p>
              <Link href={`/farms/${farmId}/store-inventory/putaway`} className={primaryCtaClass()}>
                Go to Putaway
              </Link>
            </>
          )}
        </section>

        <section className="flex flex-col gap-2 rounded-xl border border-wl-border bg-wl-surface-raised p-4 lg:col-span-2">
          <h2 className="font-serif text-base font-semibold text-wl-text">Recent Quality Decisions</h2>
          {queueQuery.isLoading ? (
            <p className="text-sm text-wl-text-secondary">Loading…</p>
          ) : recentDecisions.length === 0 ? (
            <p className="text-sm text-wl-text">No Quality decisions recorded yet.</p>
          ) : (
            <ul className="flex flex-col gap-2 text-sm">
              {recentDecisions.map((row) => (
                <li key={row.inventory_quantity_cohort_id} className="flex items-center justify-between border-b border-wl-border pb-2 last:border-0">
                  <span className="text-wl-text">
                    <span className="font-medium">{row.item_name}</span> — {row.current_state}
                  </span>
                  <span className="text-wl-text-tertiary">
                    {row.last_effective_time ? new Date(row.last_effective_time).toLocaleString() : ""}
                  </span>
                </li>
              ))}
            </ul>
          )}
          <Link href={`/farms/${farmId}/store-inventory/inventory`} className={secondaryCtaClass()}>
            View Inventory
          </Link>
        </section>
      </div>
    </div>
  );
}
