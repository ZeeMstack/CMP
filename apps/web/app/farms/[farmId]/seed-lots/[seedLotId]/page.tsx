"use client";

import Link from "next/link";
import { useParams } from "next/navigation";

import { Breadcrumbs } from "@/components/Breadcrumbs";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { BoundedDataRegion } from "@/components/layout/BoundedDataRegion";
import { LoadingSkeleton } from "@/components/LoadingSkeleton";
import { PageHeader } from "@/components/PageHeader";
import { useBatchesForSeedLot, useFarm, useSeedLot } from "@/lib/query/hooks";
import { formatDateTimeWithZoneLabel } from "@/lib/format/datetime";

export default function SeedLotDetailPage() {
  const { farmId, seedLotId } = useParams<{ farmId: string; seedLotId: string }>();
  const { data: farm } = useFarm(farmId);
  const seedLotQuery = useSeedLot(farmId, seedLotId);
  const batchesQuery = useBatchesForSeedLot(farmId, seedLotId);

  if (seedLotQuery.isLoading) return <LoadingSkeleton rows={4} label="Loading Seed Lot" />;
  if (seedLotQuery.error) return <ErrorState error={seedLotQuery.error} onRetry={() => seedLotQuery.refetch()} />;
  const seedLot = seedLotQuery.data;
  if (!seedLot) return null;

  return (
    <div>
      <PageHeader
        title={seedLot.code}
        compact
        breadcrumbs={
          <Breadcrumbs
            items={[
              { label: "Home", href: `/farms/${farmId}` },
              { label: "Seed Lots", href: `/farms/${farmId}/seed-lots` },
              { label: seedLot.code },
            ]}
          />
        }
      />

      <div className="mb-6 rounded-xl border border-wl-border bg-wl-surface-raised p-4">
        <dl className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div>
            <dt className="text-xs font-medium uppercase tracking-wide text-wl-text-secondary">Crop</dt>
            <dd className="text-sm text-wl-text">{seedLot.crop.common_name}</dd>
          </div>
          <div>
            <dt className="text-xs font-medium uppercase tracking-wide text-wl-text-secondary">Variety</dt>
            <dd className="text-sm text-wl-text">{seedLot.variety.name}</dd>
          </div>
          {seedLot.supplier_name && (
            <div>
              <dt className="text-xs font-medium uppercase tracking-wide text-wl-text-secondary">Supplier</dt>
              <dd className="text-sm text-wl-text">{seedLot.supplier_name}</dd>
            </div>
          )}
          {seedLot.supplier_lot_reference && (
            <div>
              <dt className="text-xs font-medium uppercase tracking-wide text-wl-text-secondary">Supplier lot reference</dt>
              <dd className="text-sm text-wl-text">{seedLot.supplier_lot_reference}</dd>
            </div>
          )}
          {seedLot.received_date && (
            <div>
              <dt className="text-xs font-medium uppercase tracking-wide text-wl-text-secondary">Received</dt>
              <dd className="text-sm text-wl-text">{seedLot.received_date}</dd>
            </div>
          )}
          {seedLot.expiry_date && (
            <div>
              <dt className="text-xs font-medium uppercase tracking-wide text-wl-text-secondary">Expiry</dt>
              <dd className="text-sm text-wl-text">{seedLot.expiry_date}</dd>
            </div>
          )}
        </dl>
      </div>

      <div>
        <h2 className="mb-2 font-serif text-sm font-semibold text-wl-text">Crop Batches sown from this Seed Lot</h2>
        {batchesQuery.isLoading && <LoadingSkeleton rows={2} label="Loading batches" />}
        {batchesQuery.error && <ErrorState error={batchesQuery.error} onRetry={() => batchesQuery.refetch()} />}
        {batchesQuery.data && batchesQuery.data.length === 0 && (
          <EmptyState title="No Crop Batches sown from this Seed Lot yet." />
        )}
        {batchesQuery.data && batchesQuery.data.length > 0 && (
          <BoundedDataRegion label="Linked Crop Batches">
            <ul className="divide-y divide-wl-border">
              {batchesQuery.data.map((batch) => (
                <li key={batch.id}>
                  <Link
                    href={`/farms/${farmId}/crop-batches/${batch.id}`}
                    className="flex min-h-11 items-center justify-between px-3.5 py-2 text-sm transition-colors hover:bg-wl-surface-hover"
                  >
                    <span className="font-medium text-wl-text">{batch.code}</span>
                    <span className="text-xs text-wl-text-secondary">
                      Sown {formatDateTimeWithZoneLabel(batch.sown_effective_time, farm?.timezone)}
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          </BoundedDataRegion>
        )}
      </div>
    </div>
  );
}
