"use client";

import { Breadcrumbs } from "@/components/Breadcrumbs";
import { InventoryCatalogSection } from "@/components/inventory-items/InventoryCatalogSection";
import { PageHeader } from "@/components/PageHeader";
import { StandaloneShell } from "@/components/StandaloneShell";

/** Legacy deep-link route -- no longer primary navigation (superseded by
 * Store & Inventory Setup, docs/product/CEO_ALIGNMENT_SPEC.md "Store &
 * Inventory Setup navigation"), kept live for bookmarks/farm-less tenant
 * access. Renders the same `InventoryCatalogSection` as
 * `/farms/[farmId]/store-inventory-setup/catalog`. */
export default function InventoryItemsPage() {
  return (
    <StandaloneShell>
      <PageHeader
        title="Inventory Items"
        breadcrumbs={<Breadcrumbs items={[{ label: "Home", href: "/farms" }, { label: "Inventory Items" }]} />}
      />
      <InventoryCatalogSection categoriesHref="/inventory-categories" />
    </StandaloneShell>
  );
}
