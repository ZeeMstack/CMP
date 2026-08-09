"use client";

import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";

import { BatchLineagePanel } from "@/components/BatchLineagePanel";
import { Breadcrumbs } from "@/components/Breadcrumbs";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { LoadingSkeleton } from "@/components/LoadingSkeleton";
import { PageHeader } from "@/components/PageHeader";
import { StatusBadge } from "@/components/StatusBadge";
import { formatDateTimeWithZoneLabel } from "@/lib/format/datetime";
import {
  useBatchLineage,
  useCropBatch,
  useFarm,
  useQualityHolds,
  useStageHistory,
} from "@/lib/query/hooks";

const TABS = ["overview", "history", "lineage", "quality"] as const;
type Tab = (typeof TABS)[number];

function TabLink({ farmId, batchId, tab, active, children }: { farmId: string; batchId: string; tab: Tab; active: boolean; children: React.ReactNode }) {
  return (
    <Link
      href={`/farms/${farmId}/crop-batches/${batchId}?tab=${tab}`}
      aria-current={active ? "page" : undefined}
      className={`min-h-11 border-b-2 px-3 py-2 text-sm font-medium ${
        active ? "border-brand-600 text-brand-700" : "border-transparent text-ink-muted hover:text-ink"
      }`}
    >
      {children}
    </Link>
  );
}

export default function CropBatchDetailPage() {
  const { farmId, batchId } = useParams<{ farmId: string; batchId: string }>();
  const searchParams = useSearchParams();
  const activeTab = (TABS as readonly string[]).includes(searchParams.get("tab") ?? "")
    ? (searchParams.get("tab") as Tab)
    : "overview";

  const { data: farm } = useFarm(farmId);
  // All four sections are requested concurrently on load, regardless of the
  // active tab, so switching tabs never triggers a fresh request waterfall.
  const batchQuery = useCropBatch(farmId, batchId);
  const historyQuery = useStageHistory(farmId, batchId);
  const lineageQuery = useBatchLineage(farmId, batchId);
  const qualityQuery = useQualityHolds(farmId, batchId);

  if (batchQuery.isLoading) return <LoadingSkeleton rows={6} label="Loading batch" />;
  if (batchQuery.error) return <ErrorState error={batchQuery.error} onRetry={() => batchQuery.refetch()} />;
  const batch = batchQuery.data;
  if (!batch) return null;

  const timezone = farm?.timezone;
  const origin = batch.created_by_batch_derivation_event_id
    ? "Created from a batch split/merge — see Lineage."
    : "Created directly (not derived from another batch).";

  return (
    <div>
      <PageHeader
        title={batch.code}
        breadcrumbs={
          <Breadcrumbs
            items={[
              { label: "Home", href: `/farms/${farmId}` },
              { label: "Batches", href: `/farms/${farmId}/crop-batches` },
              { label: batch.code },
            ]}
          />
        }
      />

      <nav aria-label="Batch detail sections" className="mb-6 flex gap-2 border-b border-border-subtle">
        <TabLink farmId={farmId} batchId={batchId} tab="overview" active={activeTab === "overview"}>
          Overview
        </TabLink>
        <TabLink farmId={farmId} batchId={batchId} tab="history" active={activeTab === "history"}>
          History
        </TabLink>
        <TabLink farmId={farmId} batchId={batchId} tab="lineage" active={activeTab === "lineage"}>
          Lineage
        </TabLink>
        <TabLink farmId={farmId} batchId={batchId} tab="quality" active={activeTab === "quality"}>
          Quality
        </TabLink>
      </nav>

      {activeTab === "overview" && (
        <dl className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div>
            <dt className="text-xs font-medium uppercase tracking-wide text-ink-muted">Crop</dt>
            <dd className="text-sm text-ink">
              {batch.crop.common_name}
              {batch.variety ? ` — ${batch.variety.name}` : ""}
            </dd>
          </div>
          <div>
            <dt className="text-xs font-medium uppercase tracking-wide text-ink-muted">Workflow</dt>
            <dd className="text-sm text-ink">
              {batch.workflow.name} (v{batch.version_number})
            </dd>
          </div>
          <div>
            <dt className="text-xs font-medium uppercase tracking-wide text-ink-muted">Current stage</dt>
            <dd className="text-sm text-ink">
              <StatusBadge label={batch.current_stage.name} tone="active" />
            </dd>
          </div>
          <div>
            <dt className="text-xs font-medium uppercase tracking-wide text-ink-muted">State</dt>
            <dd className="text-sm text-ink">
              <StatusBadge label={batch.state} tone={batch.state === "active" ? "active" : "closed"} />
            </dd>
          </div>
          <div>
            <dt className="text-xs font-medium uppercase tracking-wide text-ink-muted">Batch created</dt>
            <dd className="text-sm text-ink">{formatDateTimeWithZoneLabel(batch.created_effective_time, timezone)}</dd>
          </div>
          <div>
            <dt className="text-xs font-medium uppercase tracking-wide text-ink-muted">Origin</dt>
            <dd className="text-sm text-ink">{origin}</dd>
          </div>
          {batch.closed_effective_time && (
            <div>
              <dt className="text-xs font-medium uppercase tracking-wide text-ink-muted">Closed</dt>
              <dd className="text-sm text-ink">{formatDateTimeWithZoneLabel(batch.closed_effective_time, timezone)}</dd>
            </div>
          )}
          {batch.superseded_effective_time && (
            <div>
              <dt className="text-xs font-medium uppercase tracking-wide text-ink-muted">Superseded</dt>
              <dd className="text-sm text-ink">{formatDateTimeWithZoneLabel(batch.superseded_effective_time, timezone)}</dd>
            </div>
          )}
        </dl>
      )}

      {activeTab === "history" && (
        <>
          {historyQuery.isLoading && <LoadingSkeleton rows={4} label="Loading stage history" />}
          {historyQuery.error && <ErrorState error={historyQuery.error} onRetry={() => historyQuery.refetch()} />}
          {historyQuery.data && historyQuery.data.length === 0 && (
            <EmptyState title="No stage history yet" />
          )}
          {historyQuery.data && historyQuery.data.length > 0 && (
            <ul className="space-y-2">
              {historyQuery.data.map((run) => (
                <li key={run.id} className="rounded-md border border-border-subtle p-3 text-sm">
                  <span className="font-medium text-ink">{run.stage.name}</span>
                  <p className="mt-0.5 text-ink-muted">
                    Entered {formatDateTimeWithZoneLabel(run.entered_effective_time, timezone)}
                    {run.exited_effective_time
                      ? ` · Exited ${formatDateTimeWithZoneLabel(run.exited_effective_time, timezone)}`
                      : " · Current"}
                  </p>
                </li>
              ))}
            </ul>
          )}
        </>
      )}

      {activeTab === "lineage" && (
        <>
          {lineageQuery.isLoading && <LoadingSkeleton rows={4} label="Loading lineage" />}
          {lineageQuery.error && <ErrorState error={lineageQuery.error} onRetry={() => lineageQuery.refetch()} />}
          {lineageQuery.data && (
            <BatchLineagePanel lineage={lineageQuery.data} farmId={farmId} farmTimezone={timezone} />
          )}
        </>
      )}

      {activeTab === "quality" && (
        <>
          {qualityQuery.isLoading && <LoadingSkeleton rows={4} label="Loading quality holds" />}
          {qualityQuery.error && <ErrorState error={qualityQuery.error} onRetry={() => qualityQuery.refetch()} />}
          {qualityQuery.data && qualityQuery.data.length === 0 && (
            <EmptyState title="No quality holds" description="This batch has no recorded quality holds." />
          )}
          {qualityQuery.data && qualityQuery.data.length > 0 && (
            <ul className="space-y-2">
              {[...qualityQuery.data]
                .sort((a, b) => Number(b.is_open) - Number(a.is_open))
                .map((hold) => (
                  <li key={hold.id} className="rounded-md border border-border-subtle p-3 text-sm">
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-medium text-ink">{hold.reason_code}</span>
                      <StatusBadge label={hold.is_open ? "Open" : "Released"} tone={hold.is_open ? "attention" : "closed"} />
                    </div>
                    <p className="mt-0.5 text-ink-muted">{hold.reason_text}</p>
                    <p className="mt-0.5 text-xs text-ink-muted">
                      Stage: {hold.stage.name} · {formatDateTimeWithZoneLabel(hold.effective_time, timezone)}
                    </p>
                  </li>
                ))}
            </ul>
          )}
        </>
      )}
    </div>
  );
}
