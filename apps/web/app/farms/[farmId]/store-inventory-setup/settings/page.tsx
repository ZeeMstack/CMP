"use client";

import { InventoryCategoriesSection } from "@/components/inventory-categories/InventoryCategoriesSection";
import { ScopeLabel } from "@/components/store-inventory-setup/ScopeLabel";
import { UomReferenceTable } from "@/components/units-of-measure/UomReferenceTable";
import { useSelectedTenantName } from "@/lib/query/hooks";

/** UX-IA-001: Categories (tenant-wide, manageable) and Units of Measure
 * (global, read-only) share this Settings view -- both are supporting
 * configuration for the Inventory Catalog, never primary sidebar modules
 * (docs/domain/STORE_INVENTORY_MODEL.md §19). */
export default function SettingsWorkspacePage() {
  const tenantName = useSelectedTenantName();

  return (
    <div className="flex flex-col gap-10">
      <section>
        <h2 className="mb-1 font-serif text-lg font-semibold text-wl-text">Categories</h2>
        <ScopeLabel>Shared across {tenantName ?? "your tenant"}</ScopeLabel>
        <InventoryCategoriesSection />
      </section>
      <section>
        <h2 className="mb-1 font-serif text-lg font-semibold text-wl-text">Units of Measure</h2>
        <ScopeLabel>System reference</ScopeLabel>
        <UomReferenceTable />
      </section>
    </div>
  );
}
