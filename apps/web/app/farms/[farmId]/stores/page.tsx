"use client";

import { useParams } from "next/navigation";

import { Breadcrumbs } from "@/components/Breadcrumbs";
import { PageHeader } from "@/components/PageHeader";
import { StorageSection } from "@/components/stores/StorageSection";

/** Legacy deep-link route -- no longer primary navigation (superseded by
 * Store & Inventory Setup, docs/product/CEO_ALIGNMENT_SPEC.md "Store &
 * Inventory Setup navigation"), kept live for bookmarks. Renders the same
 * `StorageSection` as `/farms/[farmId]/store-inventory-setup/storage`. */
export default function StoresAndBinsPage() {
  const { farmId } = useParams<{ farmId: string }>();

  return (
    <div>
      <PageHeader
        title="Stores & Bins"
        breadcrumbs={<Breadcrumbs items={[{ label: "Home", href: `/farms/${farmId}` }, { label: "Stores & Bins" }]} />}
      />
      <StorageSection farmId={farmId} />
    </div>
  );
}
