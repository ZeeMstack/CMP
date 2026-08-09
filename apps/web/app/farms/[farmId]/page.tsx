"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useMemo } from "react";

import { ErrorState } from "@/components/ErrorState";
import { LoadingSkeleton } from "@/components/LoadingSkeleton";
import { PageHeader } from "@/components/PageHeader";
import type { LocationTreeNode } from "@/lib/api/client";
import { useCropBatches, useFarm, useLocationsTree } from "@/lib/query/hooks";

function countLocations(nodes: LocationTreeNode[]): number {
  return nodes.reduce((sum, node) => sum + 1 + countLocations(node.children), 0);
}

function groupCounts<T>(items: T[], keyOf: (item: T) => string): [string, number][] {
  const counts = new Map<string, number>();
  for (const item of items) {
    const key = keyOf(item);
    counts.set(key, (counts.get(key) ?? 0) + 1);
  }
  return [...counts.entries()].sort((a, b) => b[1] - a[1]);
}

function SummaryCard({ label, value, href }: { label: string; value: string | number; href?: string }) {
  const content = (
    <div className="rounded-lg border border-border-subtle bg-surface p-4">
      <p className="text-xs font-medium uppercase tracking-wide text-ink-muted">{label}</p>
      <p className="mt-1 text-2xl font-semibold text-ink">{value}</p>
    </div>
  );
  return href ? (
    <Link href={href} className="block hover:border-brand-300">
      {content}
    </Link>
  ) : (
    content
  );
}

export default function FarmHomePage() {
  const { farmId } = useParams<{ farmId: string }>();
  const { data: farm } = useFarm(farmId);
  const batchesQuery = useCropBatches(farmId);
  const locationsQuery = useLocationsTree(farmId);

  const stageBreakdown = useMemo(
    () => (batchesQuery.data ? groupCounts(batchesQuery.data, (b) => b.current_stage.name) : []),
    [batchesQuery.data],
  );

  if (batchesQuery.isLoading || locationsQuery.isLoading) {
    return <LoadingSkeleton rows={4} label="Loading farm overview" />;
  }

  if (batchesQuery.error) {
    return <ErrorState error={batchesQuery.error} onRetry={() => batchesQuery.refetch()} />;
  }
  if (locationsQuery.error) {
    return <ErrorState error={locationsQuery.error} onRetry={() => locationsQuery.refetch()} />;
  }

  const batches = batchesQuery.data ?? [];
  const locationCount = countLocations(locationsQuery.data ?? []);
  const activeCount = batches.filter((b) => b.state === "active").length;

  return (
    <div>
      <PageHeader title={farm ? farm.name : "Farm overview"} />
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-3">
        <SummaryCard label="Active batches" value={activeCount} href={`/farms/${farmId}/crop-batches`} />
        <SummaryCard label="Total batches" value={batches.length} href={`/farms/${farmId}/crop-batches`} />
        <SummaryCard label="Locations" value={locationCount} href={`/farms/${farmId}/locations`} />
      </div>

      <section className="mt-8">
        <h2 className="mb-3 text-sm font-semibold text-ink">Batches by stage</h2>
        {stageBreakdown.length === 0 ? (
          <p className="text-sm text-ink-muted">No batches yet.</p>
        ) : (
          <ul className="divide-y divide-border-subtle rounded-lg border border-border-subtle bg-surface">
            {stageBreakdown.map(([stage, count]) => (
              <li key={stage} className="flex items-center justify-between px-4 py-2 text-sm">
                <span className="text-ink">{stage}</span>
                <span className="font-medium text-ink-muted">{count}</span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
