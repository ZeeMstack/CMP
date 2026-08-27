"use client";

import { useParams } from "next/navigation";

import { Breadcrumbs } from "@/components/Breadcrumbs";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { LoadingSkeleton } from "@/components/LoadingSkeleton";
import { PageHeader } from "@/components/PageHeader";
import { FinishedGoodsLotListItem } from "@/components/processing/FinishedGoodsLotListItem";
import { useFinishedGoodsLots, useRecallCases } from "@/lib/query/hooks";

export default function FinishedGoodsLotsPage() {
  const { farmId } = useParams<{ farmId: string }>();
  const { data, isLoading, error, refetch } = useFinishedGoodsLots(farmId);
  const recallCasesQuery = useRecallCases(farmId);

  const sorted = [...(data ?? [])].sort((a, b) => b.effective_time.localeCompare(a.effective_time));

  return (
    <div>
      <PageHeader
        title="Finished Goods"
        breadcrumbs={
          <Breadcrumbs
            items={[
              { label: "Home", href: `/farms/${farmId}` },
              { label: "Processing", href: `/farms/${farmId}/processing` },
              { label: "Finished Goods" },
            ]}
          />
        }
      />
      {isLoading && <LoadingSkeleton rows={4} label="Loading Finished Goods Lots" />}
      {error && <ErrorState error={error} onRetry={() => refetch()} />}
      {data && data.length === 0 && (
        <EmptyState title="No Finished Goods Lots yet." description="Pack a Graded Produce Lot to create the first one." />
      )}
      {data && data.length > 0 && (
        <ul className="flex flex-col gap-3">
          {sorted.map((lot) => (
            <FinishedGoodsLotListItem key={lot.id} lot={lot} farmId={farmId} recallCases={recallCasesQuery.data} />
          ))}
        </ul>
      )}
    </div>
  );
}
