"use client";

import { MapPin } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";

import { Breadcrumbs } from "@/components/Breadcrumbs";
import { ErrorState } from "@/components/ErrorState";
import { GreenhouseStructureView } from "@/components/farm-setup/GreenhouseStructureView";
import { LoadingSkeleton } from "@/components/LoadingSkeleton";
import { PageHeader } from "@/components/PageHeader";
import { StatusBadge } from "@/components/StatusBadge";
import { classificationLabel } from "@/lib/format/greenhouseSummary";
import { useGreenhouseStructure } from "@/lib/query/hooks";

export default function GreenhouseStructurePage() {
  const { farmId, greenhouseId } = useParams<{ farmId: string; greenhouseId: string }>();
  const { data, isLoading, error, refetch } = useGreenhouseStructure(farmId, greenhouseId);

  return (
    <div>
      <PageHeader
        title={data ? data.code : "Greenhouse"}
        breadcrumbs={
          <Breadcrumbs
            items={[
              { label: "Home", href: `/farms/${farmId}` },
              { label: "Farm Setup", href: `/farms/${farmId}/farm-setup` },
              { label: data ? data.code : "…" },
            ]}
          />
        }
        actions={
          <Link
            href={`/farms/${farmId}/locations`}
            className="flex min-h-11 items-center gap-1.5 rounded-md border border-border-subtle bg-surface px-3 text-sm font-medium text-ink hover:bg-surface-subtle focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-600"
          >
            <MapPin aria-hidden="true" className="h-4 w-4" />
            View Locations &amp; Occupancy
          </Link>
        }
      />
      {isLoading && <LoadingSkeleton rows={5} label="Loading greenhouse structure" />}
      {error && <ErrorState error={error} onRetry={() => refetch()} />}
      {data && (
        <div className="flex flex-col gap-4">
          <div className="flex flex-wrap items-center gap-3 rounded-xl border border-border-subtle bg-surface p-4">
            <StatusBadge label={classificationLabel(data.classification)} tone="active" />
            <span className="text-sm text-ink-muted">{data.name}</span>
            {/* Classification is immutable after creation -- deliberately no
                edit action anywhere on this page. */}
          </div>
          <div className="rounded-xl border border-border-subtle bg-surface p-2">
            <h2 className="px-2 pt-2 font-serif text-sm font-semibold text-ink">Structure</h2>
            <GreenhouseStructureView structure={data} />
          </div>
        </div>
      )}
    </div>
  );
}
