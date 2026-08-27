"use client";

import { useParams } from "next/navigation";

import { Breadcrumbs } from "@/components/Breadcrumbs";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { LoadingSkeleton } from "@/components/LoadingSkeleton";
import { PageHeader } from "@/components/PageHeader";
import { GradedProduceLotListItem } from "@/components/processing/GradedProduceLotListItem";
import { useGradeVersionLabelMap, useGradedProduceLots, useRecallCases } from "@/lib/query/hooks";

export default function GradedProduceLotsPage() {
  const { farmId } = useParams<{ farmId: string }>();
  const { data, isLoading, error, refetch } = useGradedProduceLots(farmId);
  const { labels } = useGradeVersionLabelMap();
  const recallCasesQuery = useRecallCases(farmId);

  const sorted = [...(data ?? [])].sort((a, b) => b.effective_time.localeCompare(a.effective_time));

  return (
    <div>
      <PageHeader
        title="Graded Produce Lots"
        breadcrumbs={
          <Breadcrumbs
            items={[
              { label: "Home", href: `/farms/${farmId}` },
              { label: "Processing", href: `/farms/${farmId}/processing` },
              { label: "Graded Produce Lots" },
            ]}
          />
        }
      />
      {isLoading && <LoadingSkeleton rows={4} label="Loading Graded Produce Lots" />}
      {error && <ErrorState error={error} onRetry={() => refetch()} />}
      {data && data.length === 0 && (
        <EmptyState
          title="No Graded Produce Lots yet."
          description="Grade a Harvested Produce Lot to create the first one."
        />
      )}
      {data && data.length > 0 && (
        <ul className="flex flex-col gap-3">
          {sorted.map((lot) => (
            <GradedProduceLotListItem
              key={lot.id}
              lot={lot}
              farmId={farmId}
              gradeLabel={labels[lot.grade_definition_version_id] ?? ""}
              recallCases={recallCasesQuery.data}
            />
          ))}
        </ul>
      )}
    </div>
  );
}
