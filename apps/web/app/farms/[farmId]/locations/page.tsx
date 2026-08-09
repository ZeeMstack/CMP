"use client";

import { useParams } from "next/navigation";

import { Breadcrumbs } from "@/components/Breadcrumbs";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { LoadingSkeleton } from "@/components/LoadingSkeleton";
import { LocationTree } from "@/components/LocationTree";
import { PageHeader } from "@/components/PageHeader";
import { useLocationsTree } from "@/lib/query/hooks";

export default function LocationsPage() {
  const { farmId } = useParams<{ farmId: string }>();
  const { data, isLoading, error, refetch } = useLocationsTree(farmId);

  return (
    <div>
      <PageHeader
        title="Locations"
        breadcrumbs={
          <Breadcrumbs items={[{ label: "Home", href: `/farms/${farmId}` }, { label: "Locations" }]} />
        }
      />
      {isLoading && <LoadingSkeleton rows={6} label="Loading locations" />}
      {error && <ErrorState error={error} onRetry={() => refetch()} />}
      {data && data.length === 0 && (
        <EmptyState title="No locations yet" description="This farm has no location hierarchy configured." />
      )}
      {data && data.length > 0 && (
        <div className="rounded-lg border border-border-subtle bg-surface p-2">
          <LocationTree nodes={data} farmId={farmId} />
        </div>
      )}
    </div>
  );
}
