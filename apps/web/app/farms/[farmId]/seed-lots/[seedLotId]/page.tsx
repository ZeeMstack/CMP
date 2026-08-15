"use client";

import Link from "next/link";
import { useParams } from "next/navigation";

import { Breadcrumbs } from "@/components/Breadcrumbs";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
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

      <dl className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <div>
          <dt className="text-xs font-medium uppercase tracking-wide text-ink-muted">Crop</dt>
          <dd className="text-sm text-ink">{seedLot.crop.common_name}</dd>
        </div>
        <div>
          <dt className="text-xs font-medium uppercase tracking-wide text-ink-muted">Variety</dt>
          <dd className="text-sm text-ink">{seedLot.variety.name}</dd>
        </div>
        {seedLot.supplier_name && (
          <div>
            <dt className="text-xs font-medium uppercase tracking-wide text-ink-muted">Supplier</dt>
            <dd className="text-sm text-ink">{seedLot.supplier_name}</dd>
          </div>
        )}
        {seedLot.supplier_lot_reference && (
          <div>
            <dt className="text-xs font-medium uppercase tracking-wide text-ink-muted">Supplier lot reference</dt>
            <dd className="text-sm text-ink">{seedLot.supplier_lot_reference}</dd>
          </div>
        )}
        {seedLot.received_date && (
          <div>
            <dt className="text-xs font-medium uppercase tracking-wide text-ink-muted">Received</dt>
            <dd className="text-sm text-ink">{seedLot.received_date}</dd>
          </div>
        )}
        {seedLot.expiry_date && (
          <div>
            <dt className="text-xs font-medium uppercase tracking-wide text-ink-muted">Expiry</dt>
            <dd className="text-sm text-ink">{seedLot.expiry_date}</dd>
          </div>
        )}
      </dl>

      <div className="mt-8 border-t border-border-subtle pt-4">
        <h2 className="mb-2 text-xs font-medium uppercase tracking-wide text-ink-muted">Crop Batches sown from this Seed Lot</h2>
        {batchesQuery.isLoading && <LoadingSkeleton rows={2} label="Loading batches" />}
        {batchesQuery.error && <ErrorState error={batchesQuery.error} onRetry={() => batchesQuery.refetch()} />}
        {batchesQuery.data && batchesQuery.data.length === 0 && (
          <EmptyState title="No Crop Batches sown from this Seed Lot yet." />
        )}
        {batchesQuery.data && batchesQuery.data.length > 0 && (
          <ul className="space-y-2">
            {batchesQuery.data.map((batch) => (
              <li key={batch.id}>
                <Link
                  href={`/farms/${farmId}/crop-batches/${batch.id}`}
                  className="flex min-h-11 items-center justify-between rounded-md border border-border-subtle p-3 text-sm hover:border-brand-300"
                >
                  <span className="font-medium text-ink">{batch.code}</span>
                  <span className="text-xs text-ink-muted">
                    Sown {formatDateTimeWithZoneLabel(batch.sown_effective_time, farm?.timezone)}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
