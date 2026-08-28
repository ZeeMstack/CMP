"use client";

import { MapPin, PlusCircle } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";

import { Breadcrumbs } from "@/components/Breadcrumbs";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { GreenhouseOverviewCard } from "@/components/farm-setup/GreenhouseOverviewCard";
import { LoadingSkeleton } from "@/components/LoadingSkeleton";
import { PageHeader } from "@/components/PageHeader";
import { useGreenhouseSetupOverview } from "@/lib/query/hooks";

export default function FarmSetupOverviewPage() {
  const { farmId } = useParams<{ farmId: string }>();
  const { data, isLoading, error, refetch } = useGreenhouseSetupOverview(farmId);

  return (
    <div>
      <PageHeader
        title="Farm Setup"
        breadcrumbs={
          <Breadcrumbs items={[{ label: "Home", href: `/farms/${farmId}` }, { label: "Farm Setup" }]} />
        }
        actions={
          <div className="flex flex-wrap items-center gap-2">
            {/* Farm Setup (structure/registry) and Locations (operational
                occupancy) are deliberately distinct routes/domain purposes --
                this is a navigation affordance between them, not a merge. */}
            <Link
              href={`/farms/${farmId}/locations`}
              className="flex min-h-11 items-center gap-1.5 rounded-md border border-border-subtle bg-surface px-3 text-sm font-medium text-ink hover:bg-surface-subtle focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-600"
            >
              <MapPin aria-hidden="true" className="h-4 w-4" />
              View Locations &amp; Occupancy
            </Link>
            <Link
              href={`/farms/${farmId}/farm-setup/new`}
              className="flex min-h-11 items-center gap-1.5 rounded-md bg-brand-700 px-3 text-sm font-medium text-white hover:bg-brand-800 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-600"
            >
              <PlusCircle aria-hidden="true" className="h-4 w-4" />
              Add greenhouse
            </Link>
          </div>
        }
      />
      <p className="-mt-3 mb-6 text-xs text-ink-muted">
        This registry defines each greenhouse&apos;s physical structure. For current occupancy and what&apos;s
        placed where, see Locations &amp; Occupancy.
      </p>
      {isLoading && <LoadingSkeleton rows={4} label="Loading greenhouses" />}
      {error && <ErrorState error={error} onRetry={() => refetch()} />}
      {data && data.length === 0 && (
        <EmptyState
          title="No greenhouses configured yet."
          description="Add your first greenhouse to start configuring this farm's physical structure."
          action={
            <Link
              href={`/farms/${farmId}/farm-setup/new`}
              className="mt-2 flex min-h-11 items-center gap-1.5 rounded-md bg-brand-700 px-3 text-sm font-medium text-white hover:bg-brand-800"
            >
              <PlusCircle aria-hidden="true" className="h-4 w-4" />
              Add greenhouse
            </Link>
          }
        />
      )}
      {data && data.length > 0 && (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {data.map((item) => (
            <GreenhouseOverviewCard key={item.greenhouse_id} item={item} farmId={farmId} />
          ))}
        </div>
      )}
    </div>
  );
}
