"use client";

import { Breadcrumbs } from "@/components/Breadcrumbs";
import { InventoryCategoriesSection } from "@/components/inventory-categories/InventoryCategoriesSection";
import { PageHeader } from "@/components/PageHeader";
import { StandaloneShell } from "@/components/StandaloneShell";

/** Legacy deep-link route -- no longer primary navigation (superseded by
 * Store & Inventory Setup, docs/product/CEO_ALIGNMENT_SPEC.md "Store &
 * Inventory Setup navigation"), kept live for bookmarks/farm-less tenant
 * access. Renders the same `InventoryCategoriesSection` as
 * `/farms/[farmId]/store-inventory-setup/settings`. */
export default function InventoryCategoriesPage() {
  return (
    <StandaloneShell>
      <PageHeader
        title="Inventory Categories"
        breadcrumbs={<Breadcrumbs items={[{ label: "Home", href: "/farms" }, { label: "Inventory Categories" }]} />}
      />
      <InventoryCategoriesSection />
    </StandaloneShell>
  );
}
