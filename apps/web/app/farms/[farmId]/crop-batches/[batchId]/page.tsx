"use client";

import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";

import { OriginAndSplitsPanel } from "@/components/OriginAndSplitsPanel";
import { Breadcrumbs } from "@/components/Breadcrumbs";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { LoadingSkeleton } from "@/components/LoadingSkeleton";
import { PageHeader } from "@/components/PageHeader";
import { PlacementSummary } from "@/components/PlacementSummary";
import { QualityHoldBanner } from "@/components/QualityHoldBanner";
import { StatusBadge } from "@/components/StatusBadge";
import { describeSowingAndAge } from "@/lib/format/age";
import { formatDateTimeWithZoneLabel } from "@/lib/format/datetime";
import { humanizeEnumCode } from "@/lib/format/humanize";
import {
  useBatchLineage,
  useBatchOperationalContext,
  useCropBatch,
  useFarm,
  useQualityHolds,
  useSowings,
  useStageHistory,
} from "@/lib/query/hooks";

const TABS = ["overview", "history", "sowing", "origin", "quality"] as const;
type Tab = (typeof TABS)[number];

const TAB_LABELS: Record<Tab, string> = {
  overview: "Overview",
  history: "History",
  sowing: "Sowing",
  origin: "Origin & Splits",
  quality: "Quality",
};

function TabLink({ farmId, batchId, tab, active }: { farmId: string; batchId: string; tab: Tab; active: boolean }) {
  return (
    <Link
      href={`/farms/${farmId}/crop-batches/${batchId}?tab=${tab}`}
      aria-current={active ? "page" : undefined}
      className={`min-h-11 border-b-2 px-3 py-2 text-sm font-medium ${
        active ? "border-brand-600 text-brand-700" : "border-transparent text-ink-muted hover:text-ink"
      }`}
    >
      {TAB_LABELS[tab]}
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
  // Fixed request budget, all concurrent regardless of the active tab so
  // switching tabs never triggers a fresh request waterfall: farm, batch,
  // stage-history, lineage, quality-holds, operational-context, sowings
  // (NURSERY-OPS-001).
  const batchQuery = useCropBatch(farmId, batchId);
  const historyQuery = useStageHistory(farmId, batchId);
  const lineageQuery = useBatchLineage(farmId, batchId);
  const qualityQuery = useQualityHolds(farmId, batchId);
  const operationalQuery = useBatchOperationalContext(farmId, batchId);
  const sowingsQuery = useSowings(farmId, batchId);

  if (batchQuery.isLoading) return <LoadingSkeleton rows={6} label="Loading batch" />;
  if (batchQuery.error) return <ErrorState error={batchQuery.error} onRetry={() => batchQuery.refetch()} />;
  const batch = batchQuery.data;
  if (!batch) return null;

  const timezone = farm?.timezone;
  const operational = operationalQuery.data;
  const holdCount = operational?.open_quality_hold_count ?? 0;
  const sowingAge =
    operational && timezone
      ? describeSowingAndAge(operational.sowing_origins.length, operational.sown_effective_time, timezone)
      : null;
  const hasLineage = (lineageQuery.data?.parents.length ?? 0) > 0 || (lineageQuery.data?.children.length ?? 0) > 0;

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
        {TABS.map((tab) => (
          <TabLink key={tab} farmId={farmId} batchId={batchId} tab={tab} active={activeTab === tab} />
        ))}
      </nav>

      {activeTab === "overview" && (
        <div>
          <dl className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div>
              <dt className="text-xs font-medium uppercase tracking-wide text-ink-muted">Crop</dt>
              <dd className="text-sm text-ink">
                {batch.crop.common_name}
                {batch.variety ? ` — ${batch.variety.name}` : ""}
              </dd>
            </div>
            <div>
              <dt className="text-xs font-medium uppercase tracking-wide text-ink-muted">Current stage</dt>
              <dd className="text-sm text-ink">
                <StatusBadge label={batch.current_stage.name} tone="active" />
              </dd>
            </div>
            {batch.state !== "active" && (
              <div>
                <dt className="text-xs font-medium uppercase tracking-wide text-ink-muted">State</dt>
                <dd className="text-sm text-ink">
                  <StatusBadge label={batch.state} tone="closed" />
                </dd>
              </div>
            )}
          </dl>

          <div className="mt-4">
            {operationalQuery.isLoading && <LoadingSkeleton rows={2} label="Loading operational context" />}
            {operationalQuery.error && (
              <ErrorState error={operationalQuery.error} onRetry={() => operationalQuery.refetch()} />
            )}
            {operational && (
              <>
                <QualityHoldBanner count={holdCount} href={`/farms/${farmId}/crop-batches/${batchId}?tab=quality`} />

                <dl className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                  <div>
                    <dt className="text-xs font-medium uppercase tracking-wide text-ink-muted">Current placement</dt>
                    <dd className="text-sm text-ink">
                      <PlacementSummary placement={operational.placement} />
                    </dd>
                  </div>
                  {sowingAge && sowingAge.kind === "known" && (
                    <>
                      <div>
                        <dt className="text-xs font-medium uppercase tracking-wide text-ink-muted">Sown</dt>
                        <dd className="text-sm text-ink">{sowingAge.sownDateLabel}</dd>
                      </div>
                      <div>
                        <dt className="text-xs font-medium uppercase tracking-wide text-ink-muted">Age</dt>
                        <dd className="text-sm text-ink">
                          {sowingAge.ageDays} {sowingAge.ageDays === 1 ? "day" : "days"}
                        </dd>
                      </div>
                    </>
                  )}
                  {sowingAge && sowingAge.kind === "multiple_origins" && (
                    <div>
                      <dt className="text-xs font-medium uppercase tracking-wide text-ink-muted">Sown</dt>
                      <dd className="text-sm text-ink-muted">Multiple sowing origins</dd>
                    </div>
                  )}
                  {sowingAge && sowingAge.kind === "unknown" && (
                    <div>
                      <dt className="text-xs font-medium uppercase tracking-wide text-ink-muted">Sown</dt>
                      <dd className="text-sm text-ink-muted">Unknown</dd>
                    </div>
                  )}
                </dl>
              </>
            )}
          </div>

          {hasLineage && (
            <p className="mt-4 text-sm text-ink-muted">
              This batch has recorded origin/split history —{" "}
              <Link
                href={`/farms/${farmId}/crop-batches/${batchId}?tab=origin`}
                className="font-medium text-brand-700 hover:underline"
              >
                see Origin & Splits
              </Link>
              .
            </p>
          )}

          <div className="mt-8 border-t border-border-subtle pt-4">
            <h2 className="mb-2 text-xs font-medium uppercase tracking-wide text-ink-muted">Workflow details</h2>
            <dl className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <div>
                <dt className="text-xs text-ink-muted">Workflow</dt>
                <dd className="text-sm text-ink-muted">
                  {batch.workflow.name} (v{batch.version_number})
                </dd>
              </div>
              <div>
                <dt className="text-xs text-ink-muted">Batch created</dt>
                <dd className="text-sm text-ink-muted">{formatDateTimeWithZoneLabel(batch.created_effective_time, timezone)}</dd>
              </div>
              {batch.closed_effective_time && (
                <div>
                  <dt className="text-xs text-ink-muted">Closed</dt>
                  <dd className="text-sm text-ink-muted">{formatDateTimeWithZoneLabel(batch.closed_effective_time, timezone)}</dd>
                </div>
              )}
              {batch.superseded_effective_time && (
                <div>
                  <dt className="text-xs text-ink-muted">Superseded</dt>
                  <dd className="text-sm text-ink-muted">{formatDateTimeWithZoneLabel(batch.superseded_effective_time, timezone)}</dd>
                </div>
              )}
            </dl>
          </div>
        </div>
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

      {activeTab === "sowing" && (
        <>
          {sowingsQuery.isLoading && <LoadingSkeleton rows={3} label="Loading sowing record" />}
          {sowingsQuery.error && <ErrorState error={sowingsQuery.error} onRetry={() => sowingsQuery.refetch()} />}
          {sowingsQuery.data && sowingsQuery.data.length === 0 && (
            <EmptyState title="No Sowing record" description="This batch was not created via the Sowing command." />
          )}
          {sowingsQuery.data?.map((event) => (
            <div key={event.id} className="flex flex-col gap-4">
              <dl className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                <div>
                  <dt className="text-xs font-medium uppercase tracking-wide text-ink-muted">Seed Lot</dt>
                  <dd className="text-sm text-ink">{event.lines[0]?.seed_lot.code ?? "—"}</dd>
                </div>
                <div>
                  <dt className="text-xs font-medium uppercase tracking-wide text-ink-muted">Occurred at</dt>
                  <dd className="text-sm text-ink">{formatDateTimeWithZoneLabel(event.effective_time, timezone)}</dd>
                </div>
                {event.seeding_station && (
                  <div>
                    <dt className="text-xs font-medium uppercase tracking-wide text-ink-muted">Seeding Station</dt>
                    <dd className="text-sm text-ink">{event.seeding_station.code}</dd>
                  </div>
                )}
                {event.seeding_machine && (
                  <div>
                    <dt className="text-xs font-medium uppercase tracking-wide text-ink-muted">Seeding Machine</dt>
                    <dd className="text-sm text-ink">{event.seeding_machine.code} (farm-level equipment)</dd>
                  </div>
                )}
                <div>
                  <dt className="text-xs font-medium uppercase tracking-wide text-ink-muted">Total seeds sown</dt>
                  <dd className="text-sm text-ink">{event.total_seeds_sown.toLocaleString()}</dd>
                </div>
              </dl>
              <div>
                <h3 className="mb-2 text-xs font-medium uppercase tracking-wide text-ink-muted">
                  Seed Trays ({event.lines.length})
                </h3>
                <ul className="divide-y divide-border-subtle">
                  {event.lines.map((line) => (
                    <li key={line.id} className="flex items-center justify-between py-1.5 text-sm">
                      <span className="text-ink">{line.carrier.code}</span>
                      <span className="text-ink-muted">{line.seed_count} seeds</span>
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          ))}
        </>
      )}

      {activeTab === "origin" && (
        <>
          {lineageQuery.isLoading && <LoadingSkeleton rows={4} label="Loading origin and splits" />}
          {lineageQuery.error && <ErrorState error={lineageQuery.error} onRetry={() => lineageQuery.refetch()} />}
          {lineageQuery.data && <OriginAndSplitsPanel lineage={lineageQuery.data} farmId={farmId} />}
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
                      <span className="font-medium text-ink">{humanizeEnumCode(hold.reason_code)}</span>
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
