"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useMemo } from "react";

import { ErrorState } from "@/components/ErrorState";
import { LoadingSkeleton } from "@/components/LoadingSkeleton";
import { PageHeader } from "@/components/PageHeader";
import { computeHomeKpis } from "@/lib/format/homeKpis";
import { humanizeEnumCode } from "@/lib/format/humanize";
import { groupBatchesByStage } from "@/lib/format/stageOrder";
import { useFarm, useOperationalSummary } from "@/lib/query/hooks";

function SummaryCard({ label, value, href, caption }: { label: string; value: string | number; href?: string; caption?: string }) {
  const cardClass = `h-full rounded-xl border border-border-subtle bg-surface p-4 transition-colors ${href ? "hover:border-brand-300" : ""}`;
  const content = (
    <div className={cardClass}>
      <p className="text-xs font-semibold uppercase tracking-wide text-ink-muted">{label}</p>
      <p className="mt-1 font-serif text-2xl font-semibold text-ink">{value}</p>
      {caption && <p className="mt-0.5 text-xs text-ink-muted">{caption}</p>}
    </div>
  );
  return href ? (
    <Link
      href={href}
      className="block rounded-xl focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-600"
    >
      {content}
    </Link>
  ) : (
    content
  );
}

export default function FarmHomePage() {
  const { farmId } = useParams<{ farmId: string }>();
  const { data: farm } = useFarm(farmId);
  // Home's first-load request budget is exactly 2: farm + active
  // operational summary. No other network call belongs on this page.
  const summaryQuery = useOperationalSummary(farmId, "active");

  // Grouped by (stage_category, stage name) -- not stage ID (which would
  // fragment equivalent configured workflows into separate rows for no
  // reason) and not name alone (which would silently merge two genuinely
  // different stages, e.g. a nursery "Growing" step and a production
  // "Growing" step, that only happen to share a display name).
  const stageBreakdown = useMemo(
    () => (summaryQuery.data ? groupBatchesByStage(summaryQuery.data) : []),
    [summaryQuery.data],
  );
  // If two groups share a visible name but differ by category, disambiguate
  // with a minimal, humanized category suffix -- never raw category codes.
  const nameOccurrences = useMemo(() => {
    const counts = new Map<string, number>();
    for (const group of stageBreakdown) counts.set(group.name, (counts.get(group.name) ?? 0) + 1);
    return counts;
  }, [stageBreakdown]);

  if (summaryQuery.isLoading) {
    return <LoadingSkeleton rows={4} label="Loading farm overview" />;
  }

  if (summaryQuery.error) {
    // Never silently fall back to a misleading FE-001-style calculation --
    // if the operational summary fails, say so plainly.
    return <ErrorState error={summaryQuery.error} onRetry={() => summaryQuery.refetch()} />;
  }

  const activeBatches = summaryQuery.data ?? [];
  const { activeCount, harvestReadyCount, openHoldBatchCount } = computeHomeKpis(activeBatches);

  return (
    <div>
      <PageHeader title={farm ? farm.name : "Farm overview"} />
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-3">
        <SummaryCard label="Active batches" value={activeCount} href={`/farms/${farmId}/crop-batches`} />
        <SummaryCard label="Harvest ready" value={harvestReadyCount} href={`/farms/${farmId}/crop-batches`} />
        <SummaryCard
          label="Batches with open quality holds"
          value={openHoldBatchCount}
          href={`/farms/${farmId}/crop-batches`}
          caption={openHoldBatchCount === 1 ? "1 batch affected" : `${openHoldBatchCount} batches affected`}
        />
      </div>

      <section className="mt-8">
        <h2 className="mb-3 font-serif text-base font-semibold text-ink">Active production by stage</h2>
        {stageBreakdown.length === 0 ? (
          <p className="text-sm text-ink-muted">No active batches yet.</p>
        ) : (
          <ul className="divide-y divide-border-subtle rounded-xl border border-border-subtle bg-surface">
            {stageBreakdown.map((stage) => {
              const needsDisambiguation = (nameOccurrences.get(stage.name) ?? 0) > 1;
              return (
                <li
                  key={`${stage.category}-${stage.name}`}
                  className="flex items-center justify-between gap-3 px-4 py-2.5 text-sm"
                >
                  <span className="text-ink">
                    {stage.name}
                    {needsDisambiguation && (
                      <span className="text-ink-muted"> · {humanizeEnumCode(stage.category)}</span>
                    )}
                  </span>
                  <span className="inline-flex min-w-8 shrink-0 items-center justify-center rounded-full bg-brand-100 px-2 py-0.5 text-xs font-semibold text-brand-800">
                    {stage.count}
                  </span>
                </li>
              );
            })}
          </ul>
        )}
      </section>
    </div>
  );
}
