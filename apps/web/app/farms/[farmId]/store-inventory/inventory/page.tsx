"use client";

import { useParams } from "next/navigation";
import { Fragment, useState } from "react";

import { Breadcrumbs } from "@/components/Breadcrumbs";
import { PageHeader } from "@/components/PageHeader";
import { useInventoryItems, useItemExistenceProvenance, useItemsExistenceSummary } from "@/lib/query/hooks";

function ProvenanceRows({ itemId }: { itemId: string }) {
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
          <tr key={row.inventory_quantity_cohort_id} className="border-t border-wl-border">
            <td className="p-2 font-mono text-wl-text-tertiary">{row.inventory_quantity_cohort_id.slice(0, 8)}</td>
            <td className="p-2 text-wl-text">{row.balance}</td>
            <td className="p-2 text-wl-text-tertiary">Received at Farm {row.received_at_farm_id.slice(0, 8)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/** STORE-INV-002A.2: company-wide existence + usable quantity, by item.
 * Never labels usable as "available" -- Reservation does not exist yet.
 * "Received at <Farm>" is provenance only, never a current-location claim;
 * the Farm selector never filters these company-wide totals (docs/domain/
 * STORE_INVENTORY_MODEL.md §13/§18). */
export default function StoreInventoryInventoryPage() {
  const { farmId } = useParams<{ farmId: string }>();
  const itemsQuery = useInventoryItems({ status: "active" });
  const items = itemsQuery.data ?? [];
  const summary = useItemsExistenceSummary(items.map((i) => i.id));
  const [expandedItemId, setExpandedItemId] = useState<string | null>(null);

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
        Current Store/Bin location is not yet tracked (planned for a future release). Selecting a different Farm
        does not change the totals below.
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
                        <td colSpan={4} className="p-0">
                          <ProvenanceRows itemId={item.id} />
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
