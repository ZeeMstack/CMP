"use client";

import { Breadcrumbs } from "@/components/Breadcrumbs";
import { ErrorState } from "@/components/ErrorState";
import { LoadingSkeleton } from "@/components/LoadingSkeleton";
import { PageHeader } from "@/components/PageHeader";
import { StandaloneShell } from "@/components/StandaloneShell";
import { useUoms } from "@/lib/query/hooks";

/** docs/domain/STORE_INVENTORY_MODEL.md §6: permanently read-only system
 * reference -- no create/edit/delete control, no `.manage` permission.
 * Exists so operators/admins can see the system UOM catalog and so the
 * Inventory Item form has human-readable units to select from. */
export default function UnitsOfMeasurePage() {
  const uomsQuery = useUoms();
  const uoms = uomsQuery.data ?? [];

  return (
    <StandaloneShell>
      <PageHeader
        title="Units of Measure"
        breadcrumbs={<Breadcrumbs items={[{ label: "Home", href: "/farms" }, { label: "Units of Measure" }]} />}
      />
      <p className="-mt-3 mb-6 text-xs text-ink-muted">
        System-controlled reference units. This list is not tenant-configurable.
      </p>

      {uomsQuery.isLoading && <LoadingSkeleton rows={4} label="Loading units of measure" />}
      {uomsQuery.error && <ErrorState error={uomsQuery.error} onRetry={() => uomsQuery.refetch()} />}
      {!uomsQuery.isLoading && !uomsQuery.error && (
        <div className="overflow-x-auto rounded-xl border border-border-subtle bg-surface">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-border-subtle bg-surface-subtle text-xs uppercase text-ink-muted">
              <tr>
                <th className="px-4 py-2 font-medium">Code</th>
                <th className="px-4 py-2 font-medium">Name</th>
                <th className="px-4 py-2 font-medium">Quantity kind</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border-subtle">
              {uoms.map((uom) => (
                <tr key={uom.id} className="hover:bg-surface-subtle">
                  <td className="px-4 py-2 font-medium text-ink">{uom.code}</td>
                  <td className="px-4 py-2 text-ink">{uom.name}</td>
                  <td className="px-4 py-2 capitalize text-ink">{uom.quantity_kind}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </StandaloneShell>
  );
}
