"use client";

import Link from "next/link";
import { useParams } from "next/navigation";

import { ScopeLabel } from "@/components/store-inventory-setup/ScopeLabel";
import { countStoreHierarchy, extractStoreRoots } from "@/lib/format/storeTree";
import { useFarm, useInventoryCategories, useInventoryItems, useLocationsTree, useSelectedTenantName, useUoms } from "@/lib/query/hooks";

function primaryCtaClass(): string {
  return "mt-1 inline-flex h-9 items-center gap-1.5 self-start rounded-[7px] bg-wl-brand px-4 text-sm font-medium text-wl-text-on-brand hover:bg-wl-brand-hover active:bg-wl-brand-pressed";
}

function secondaryCtaClass(): string {
  return "mt-1 inline-flex h-9 items-center gap-1.5 self-start rounded-[7px] border border-wl-border-strong bg-wl-surface-raised px-4 text-sm font-medium text-wl-text hover:bg-wl-surface-hover";
}

/** UX-IA-001: the workspace's Overview -- a factual Setup Summary, never a
 * global "Store & Inventory Ready" claim (docs/domain/STORE_INVENTORY_MODEL.md
 * §19: no domain evidence yet exists for total readiness -- Goods Receipt
 * and physical stock balances are STORE-INV-002A/002B, not built here).
 * Each card shows configured state, a missing prerequisite, or counts plus
 * a next action -- never a score, percentage, or green-check "ready" state. */
export default function StoreInventorySetupOverviewPage() {
  const { farmId } = useParams<{ farmId: string }>();
  const base = `/farms/${farmId}/store-inventory-setup`;

  const { data: farm } = useFarm(farmId);
  const tenantName = useSelectedTenantName();
  const treeQuery = useLocationsTree(farmId);
  const itemsQuery = useInventoryItems();
  const categoriesQuery = useInventoryCategories();
  const uomsQuery = useUoms();

  const storeRoots = extractStoreRoots(treeQuery.data ?? []);
  const storeCounts = countStoreHierarchy(storeRoots);

  const activeCategories = (categoriesQuery.data ?? []).filter((c) => c.status === "active");
  const activeItems = (itemsQuery.data ?? []).filter((i) => i.status === "active");
  const catalogDataReady = !categoriesQuery.isLoading && !itemsQuery.isLoading;

  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
      <section className="flex flex-col gap-1 rounded-xl border border-wl-border bg-wl-surface-raised p-4">
        <h2 className="font-serif text-base font-semibold text-wl-text">Storage</h2>
        <ScopeLabel>For {farm ? farm.name : "this farm"}</ScopeLabel>
        {treeQuery.isLoading ? (
          <p className="text-sm text-wl-text-secondary">Loading…</p>
        ) : storeCounts.activeStores === 0 ? (
          <>
            <p className="text-sm text-wl-text">No active Store configured</p>
            <Link href={`${base}/storage`} className={primaryCtaClass()}>
              Create first Store
            </Link>
          </>
        ) : (
          <>
            <p className="text-sm text-wl-text">
              {storeCounts.activeStores} active {storeCounts.activeStores === 1 ? "Store" : "Stores"} · {storeCounts.areas}{" "}
              {storeCounts.areas === 1 ? "Area" : "Areas"} · {storeCounts.racks} {storeCounts.racks === 1 ? "Rack" : "Racks"} ·{" "}
              {storeCounts.bins} {storeCounts.bins === 1 ? "Bin" : "Bins"}
            </p>
            <Link href={`${base}/storage`} className={secondaryCtaClass()}>
              Manage storage
            </Link>
          </>
        )}
      </section>

      <section className="flex flex-col gap-1 rounded-xl border border-wl-border bg-wl-surface-raised p-4">
        <h2 className="font-serif text-base font-semibold text-wl-text">Inventory Catalog</h2>
        <ScopeLabel>Shared across {tenantName ?? "your tenant"}</ScopeLabel>
        {!catalogDataReady ? (
          <p className="text-sm text-wl-text-secondary">Loading…</p>
        ) : activeCategories.length === 0 ? (
          <>
            <p className="text-sm text-wl-text">No active Categories</p>
            <Link href={`${base}/settings`} className={primaryCtaClass()}>
              Create first Category
            </Link>
          </>
        ) : activeItems.length === 0 ? (
          <>
            <p className="text-sm text-wl-text">
              {activeCategories.length} active {activeCategories.length === 1 ? "Category" : "Categories"}
            </p>
            <p className="text-sm text-wl-text">0 Inventory Items</p>
            <Link href={`${base}/catalog`} className={primaryCtaClass()}>
              Add first Inventory Item
            </Link>
          </>
        ) : (
          <>
            <p className="text-sm text-wl-text">
              {activeItems.length} active {activeItems.length === 1 ? "Item" : "Items"} · {activeCategories.length} active{" "}
              {activeCategories.length === 1 ? "Category" : "Categories"}
            </p>
            <Link href={`${base}/catalog`} className={secondaryCtaClass()}>
              Manage inventory catalog
            </Link>
          </>
        )}
      </section>

      <section className="flex flex-col gap-1 rounded-xl border border-wl-border bg-wl-surface-raised p-4 lg:col-span-2">
        <h2 className="font-serif text-base font-semibold text-wl-text">Units of Measure</h2>
        <ScopeLabel>System reference</ScopeLabel>
        <p className="text-sm text-wl-text">
          {uomsQuery.isLoading ? "Loading…" : `${(uomsQuery.data ?? []).length} units of measure available`}
        </p>
        <Link href={`${base}/settings`} className={secondaryCtaClass()}>
          View units
        </Link>
      </section>
    </div>
  );
}
