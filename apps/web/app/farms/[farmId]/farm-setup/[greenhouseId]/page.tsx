"use client";

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
      />
      {isLoading && <LoadingSkeleton rows={5} label="Loading greenhouse structure" />}
      {error && <ErrorState error={error} onRetry={() => refetch()} />}
      {data && (
        <div className="flex flex-col gap-4">
          <div className="flex flex-wrap items-center gap-2 rounded-lg border border-border-subtle bg-surface p-4">
            <StatusBadge label={classificationLabel(data.classification)} tone="active" />
            <span className="text-sm text-ink-muted">{data.name}</span>
            {/* Classification is immutable after creation -- deliberately no
                edit action anywhere on this page. */}
          </div>
          <div className="rounded-lg border border-border-subtle bg-surface p-2">
            <GreenhouseStructureView structure={data} />
          </div>
        </div>
      )}
    </div>
  );
}
