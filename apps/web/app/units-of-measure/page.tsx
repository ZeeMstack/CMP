"use client";

import { Breadcrumbs } from "@/components/Breadcrumbs";
import { PageHeader } from "@/components/PageHeader";
import { StandaloneShell } from "@/components/StandaloneShell";
import { UomReferenceTable } from "@/components/units-of-measure/UomReferenceTable";

/** Legacy deep-link route -- no longer primary navigation (superseded by
 * Store & Inventory Setup, docs/product/CEO_ALIGNMENT_SPEC.md "Store &
 * Inventory Setup navigation"), kept live for bookmarks/farm-less tenant
 * access. Renders the same `UomReferenceTable` as
 * `/farms/[farmId]/store-inventory-setup/settings`. */
export default function UnitsOfMeasurePage() {
  return (
    <StandaloneShell>
      <PageHeader
        title="Units of Measure"
        breadcrumbs={<Breadcrumbs items={[{ label: "Home", href: "/farms" }, { label: "Units of Measure" }]} />}
      />
      <UomReferenceTable />
    </StandaloneShell>
  );
}
