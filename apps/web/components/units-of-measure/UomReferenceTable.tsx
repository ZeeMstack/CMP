"use client";

import { ErrorState } from "@/components/ErrorState";
import { LoadingSkeleton } from "@/components/LoadingSkeleton";
import {
  tableBodyDividerClass,
  tableHeadRowClass,
  tableRowHoverClass,
  tableTdClass,
  tableThClass,
  tableWrapperClass,
} from "@/components/ui/table";
import { useUoms } from "@/lib/query/hooks";

/** docs/domain/STORE_INVENTORY_MODEL.md §6: permanently read-only system
 * reference -- no create/edit/delete control, no `.manage` permission.
 * Exists so operators/admins can see the system UOM catalog and so the
 * Inventory Item form has human-readable units to select from. UX-IA-001:
 * extracted, unchanged, from the pre-existing `/units-of-measure` page --
 * rendered by both that legacy route and the new workspace `settings`
 * child route's "System reference" section. */
export function UomReferenceTable() {
  const uomsQuery = useUoms();
  const uoms = uomsQuery.data ?? [];

  return (
    <div>
      <p className="mb-4 text-xs text-wl-text-secondary">
        System-controlled reference units. This list is not tenant-configurable.
      </p>

      {uomsQuery.isLoading && <LoadingSkeleton rows={4} label="Loading units of measure" />}
      {uomsQuery.error && <ErrorState error={uomsQuery.error} onRetry={() => uomsQuery.refetch()} />}
      {!uomsQuery.isLoading && !uomsQuery.error && (
        <div className={tableWrapperClass}>
          <table className="w-full text-left text-sm">
            <thead>
              <tr className={tableHeadRowClass}>
                <th className={tableThClass}>Code</th>
                <th className={tableThClass}>Name</th>
                <th className={tableThClass}>Quantity kind</th>
              </tr>
            </thead>
            <tbody className={tableBodyDividerClass}>
              {uoms.map((uom) => (
                <tr key={uom.id} className={tableRowHoverClass}>
                  <td className={`${tableTdClass} font-medium text-wl-text`}>{uom.code}</td>
                  <td className={`${tableTdClass} text-wl-text`}>{uom.name}</td>
                  <td className={`${tableTdClass} capitalize text-wl-text`}>{uom.quantity_kind}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
