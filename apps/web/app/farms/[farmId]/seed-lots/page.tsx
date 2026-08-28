"use client";

import { PlusCircle } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";

import { Breadcrumbs } from "@/components/Breadcrumbs";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { LoadingSkeleton } from "@/components/LoadingSkeleton";
import { PageHeader } from "@/components/PageHeader";
import { SeedLotCard } from "@/components/nursery/SeedLotCard";
import { useSeedLots } from "@/lib/query/hooks";

export default function SeedLotsPage() {
  const { farmId } = useParams<{ farmId: string }>();
  const { data, isLoading, error, refetch } = useSeedLots(farmId);

  return (
    <div>
      <PageHeader
        title="Seed Lots"
        breadcrumbs={<Breadcrumbs items={[{ label: "Home", href: `/farms/${farmId}` }, { label: "Seed Lots" }]} />}
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <Link
              href={`/farms/${farmId}/nursery/sowings/new`}
              className="flex min-h-11 items-center gap-1.5 rounded-md border border-border-subtle bg-surface px-3 text-sm font-medium text-ink hover:bg-surface-subtle focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-600"
            >
              Go to Seeding
            </Link>
            <Link
              href={`/farms/${farmId}/seed-lots/new`}
              className="flex min-h-11 items-center gap-1.5 rounded-md bg-brand-700 px-3 text-sm font-medium text-white hover:bg-brand-800 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-600"
            >
              <PlusCircle aria-hidden="true" className="h-4 w-4" />
              Add Seed Lot
            </Link>
          </div>
        }
      />
      <p className="mb-4 text-xs text-ink-muted">
        A Seed Lot records where the seed for a Sowing came from — a traceability source, not seed stock on hand.
        Not shown in the main menu, but reachable here and from Seeding whenever a Sowing needs one.
      </p>
      {isLoading && <LoadingSkeleton rows={4} label="Loading Seed Lots" />}
      {error && <ErrorState error={error} onRetry={() => refetch()} />}
      {data && data.length === 0 && (
        <EmptyState
          title="No Seed Lots registered yet."
          description="Add your first Seed Lot before sowing a Crop Batch."
          action={
            <Link
              href={`/farms/${farmId}/seed-lots/new`}
              className="mt-2 flex min-h-11 items-center gap-1.5 rounded-md bg-brand-700 px-3 text-sm font-medium text-white hover:bg-brand-800"
            >
              <PlusCircle aria-hidden="true" className="h-4 w-4" />
              Add Seed Lot
            </Link>
          }
        />
      )}
      {data && data.length > 0 && (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {data.map((seedLot) => (
            <SeedLotCard key={seedLot.id} seedLot={seedLot} farmId={farmId} />
          ))}
        </div>
      )}
    </div>
  );
}
