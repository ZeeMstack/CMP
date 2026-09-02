"use client";

import { ClipboardCheck, MapPin, PlusCircle } from "lucide-react";
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
        description="This registry defines each greenhouse's physical structure. For current occupancy and what's placed where, see Locations & Occupancy."
        breadcrumbs={
          <Breadcrumbs items={[{ label: "Home", href: `/farms/${farmId}` }, { label: "Farm Setup" }]} />
        }
        actions={
          <div className="flex flex-wrap items-center gap-1">
            {/* Farm Setup (structure/registry) and Locations (operational
                occupancy) are deliberately distinct routes/domain purposes --
                this is a navigation affordance between them, not a merge.
                Restrained bordered secondary controls, deliberately less
                visually dominant than the "Add greenhouse" primary CTA --
                see PILOT-UX-001A2-R2 (final polish) section 5. */}
            <Link
              href={`/farms/${farmId}/setup-readiness`}
              className="flex h-9 items-center gap-1.5 rounded-[7px] border border-wl-border-strong bg-wl-surface-raised px-3 text-sm font-medium text-wl-text hover:bg-wl-surface-hover focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-wl-focus"
            >
              <ClipboardCheck aria-hidden="true" className="h-4 w-4" />
              Setup Readiness
            </Link>
            <Link
              href={`/farms/${farmId}/locations`}
              className="flex h-9 items-center gap-1.5 rounded-[7px] border border-wl-border-strong bg-wl-surface-raised px-3 text-sm font-medium text-wl-text hover:bg-wl-surface-hover focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-wl-focus"
            >
              <MapPin aria-hidden="true" className="h-4 w-4" />
              View Locations &amp; Occupancy
            </Link>
            <Link
              href={`/farms/${farmId}/farm-setup/new`}
              className="ml-1 flex h-9 items-center gap-1.5 rounded-[7px] bg-wl-brand px-4 text-sm font-medium text-wl-text-on-brand hover:bg-wl-brand-hover active:bg-wl-brand-pressed focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-wl-focus"
            >
              <PlusCircle aria-hidden="true" className="h-4 w-4" />
              Add greenhouse
            </Link>
          </div>
        }
      />
      {isLoading && <LoadingSkeleton rows={4} label="Loading greenhouses" />}
      {error && <ErrorState error={error} onRetry={() => refetch()} />}
      {data && data.length === 0 && (
        <EmptyState
          title="No greenhouses configured yet."
          description="Add your first greenhouse to start configuring this farm's physical structure."
          action={
            <Link
              href={`/farms/${farmId}/farm-setup/new`}
              className="mt-2 flex h-9 items-center gap-1.5 rounded-[7px] bg-wl-brand px-4 text-sm font-medium text-wl-text-on-brand hover:bg-wl-brand-hover active:bg-wl-brand-pressed"
            >
              <PlusCircle aria-hidden="true" className="h-4 w-4" />
              Add greenhouse
            </Link>
          }
        />
      )}
      {data && data.length > 0 && (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {data.map((item) => (
            <GreenhouseOverviewCard key={item.greenhouse_id} item={item} farmId={farmId} />
          ))}
        </div>
      )}
    </div>
  );
}
