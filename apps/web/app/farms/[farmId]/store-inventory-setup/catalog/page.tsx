"use client";

import { useParams } from "next/navigation";

import { InventoryCatalogSection } from "@/components/inventory-items/InventoryCatalogSection";
import { ScopeLabel } from "@/components/store-inventory-setup/ScopeLabel";
import { useSelectedTenantName } from "@/lib/query/hooks";

export default function CatalogWorkspacePage() {
  const { farmId } = useParams<{ farmId: string }>();
  const tenantName = useSelectedTenantName();

  return (
    <div>
      <ScopeLabel>Shared across {tenantName ?? "your tenant"}</ScopeLabel>
      <InventoryCatalogSection categoriesHref={`/farms/${farmId}/store-inventory-setup/settings`} />
    </div>
  );
}
