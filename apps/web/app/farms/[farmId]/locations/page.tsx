"use client";

import { Wrench } from "lucide-react";
import Link from "next/link";
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
        actions={
          <Link
            href={`/farms/${farmId}/farm-setup`}
            className="flex min-h-11 items-center gap-1.5 rounded-md border border-border-subtle bg-surface px-3 text-sm font-medium text-ink hover:bg-surface-subtle focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-600"
          >
            <Wrench aria-hidden="true" className="h-4 w-4" />
            View Farm Setup
          </Link>
        }
      />
      {/* This is the operational occupancy view (what's placed where, right
          now) -- distinct from Farm Setup, which defines physical
          structure. Structural edits happen there, not here. */}
      <p className="-mt-3 mb-6 text-xs text-ink-muted">
        Current occupancy across this farm&apos;s location hierarchy. To change greenhouse structure, use Farm Setup.
      </p>
      {isLoading && <LoadingSkeleton rows={6} label="Loading locations" />}
      {error && <ErrorState error={error} onRetry={() => refetch()} />}
      {data && data.length === 0 && (
        <EmptyState title="No locations yet" description="This farm has no location hierarchy configured." />
      )}
      {data && data.length > 0 && (
        <div className="rounded-xl border border-border-subtle bg-surface p-2">
          <LocationTree nodes={data} farmId={farmId} />
        </div>
      )}
    </div>
  );
}
