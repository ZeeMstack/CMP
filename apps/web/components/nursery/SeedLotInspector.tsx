import Link from "next/link";

import { InspectorEmptyState, InspectorShell } from "@/components/layout/InspectorShell";
import type { SeedLotRead } from "@/lib/api/client";
import { useBatchesForSeedLot } from "@/lib/query/hooks";

/** UX-OPS-001B: the Seed Lot register's selected-item inspector -- compact
 * identity/provenance facts plus the linked-Batch activity fact (ticket
 * §6.3), fetched only for the ONE selected Seed Lot rather than N+1 across
 * every register row. Links to the existing dedicated detail page for the
 * full facts/history rather than duplicating it here. */
export function SeedLotInspector({ seedLot, farmId, onClose }: { seedLot: SeedLotRead | null; farmId: string; onClose: () => void }) {
  const batchesQuery = useBatchesForSeedLot(farmId, seedLot?.id ?? "", Boolean(seedLot));

  if (!seedLot) return <InspectorEmptyState />;

  return (
    <InspectorShell title={seedLot.code} subtitle={`${seedLot.crop.common_name} — ${seedLot.variety.name}`} onClose={onClose}>
      <dl className="flex flex-col gap-2 text-sm">
        {seedLot.supplier_name && (
          <div>
            <dt className="text-xs text-wl-text-secondary">Supplier</dt>
            <dd className="text-wl-text">{seedLot.supplier_name}</dd>
          </div>
        )}
        {seedLot.received_date && (
          <div>
            <dt className="text-xs text-wl-text-secondary">Received</dt>
            <dd className="text-wl-text">{seedLot.received_date}</dd>
          </div>
        )}
        {seedLot.expiry_date && (
          <div>
            <dt className="text-xs text-wl-text-secondary">Expiry</dt>
            <dd className="text-wl-text">{seedLot.expiry_date}</dd>
          </div>
        )}
        <div>
          <dt className="text-xs text-wl-text-secondary">Linked Batches</dt>
          <dd className="text-wl-text">
            {batchesQuery.isLoading
              ? "Loading…"
              : batchesQuery.error
                ? "Unavailable"
                : `${(batchesQuery.data ?? []).length} sown from this Seed Lot`}
          </dd>
        </div>
      </dl>
      <Link
        href={`/farms/${farmId}/seed-lots/${seedLot.id}`}
        className="inline-block text-sm font-medium text-wl-brand hover:underline"
      >
        Open full detail
      </Link>
    </InspectorShell>
  );
}
