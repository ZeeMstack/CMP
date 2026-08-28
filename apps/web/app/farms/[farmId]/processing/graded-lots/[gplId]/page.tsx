"use client";

import { useParams } from "next/navigation";

import { Breadcrumbs } from "@/components/Breadcrumbs";
import { ErrorState } from "@/components/ErrorState";
import { LoadingSkeleton } from "@/components/LoadingSkeleton";
import { PageHeader } from "@/components/PageHeader";
import { findOpenRecallCase, RecallBadge } from "@/components/processing/RecallBadge";
import {
  useGradeVersionLabelMap, useGradedProduceLot, useGradedProduceLotBalance, useGradedProduceLotLedger,
  useGradingEvent, useRecallCases,
} from "@/lib/query/hooks";

const GPL_LEDGER_ENTRY_KIND_LABEL: Record<string, string> = {
  grading_receipt: "Grading receipt",
  packing_consumption: "Packing consumption",
  grading_reversal: "Grading reversed",
  packing_reversal: "Packing reversed",
};

/** POSTHARVEST-OPS-001G: Graded Produce Lot detail -- exact grade, source
 * Harvested Produce Lot (resolved via its own Grading Event, since a GPL
 * only carries `grading_event_id`), original vs. current available
 * weight/count, effective time, ledger, and recall status. */
export default function GradedProduceLotDetailPage() {
  const { farmId, gplId } = useParams<{ farmId: string; gplId: string }>();
  const gplQuery = useGradedProduceLot(farmId, gplId);
  const balanceQuery = useGradedProduceLotBalance(farmId, gplId);
  const ledgerQuery = useGradedProduceLotLedger(farmId, gplId);
  const { labels } = useGradeVersionLabelMap();
  const recallCasesQuery = useRecallCases(farmId);

  const gradingEventId = gplQuery.data?.grading_event_id ?? null;
  const gradingEventQuery = useGradingEvent(farmId, gradingEventId);

  if (gplQuery.isLoading) return <LoadingSkeleton rows={4} label="Loading Graded Produce Lot" />;
  if (gplQuery.error) return <ErrorState error={gplQuery.error} onRetry={() => gplQuery.refetch()} />;
  const lot = gplQuery.data;
  if (!lot) return null;

  const recallCase = findOpenRecallCase(recallCasesQuery.data, "graded_produce_lot_id", lot.id);
  const isCountMode = lot.original_received_whole_unit_count != null;

  return (
    <div>
      <PageHeader
        title={lot.code}
        breadcrumbs={
          <Breadcrumbs
            items={[
              { label: "Home", href: `/farms/${farmId}` },
              { label: "Processing", href: `/farms/${farmId}/processing` },
              { label: "Graded Produce Lots", href: `/farms/${farmId}/processing/graded-lots` },
              { label: lot.code },
            ]}
          />
        }
      />

      <div className="flex flex-col gap-4">
        {recallCase && <RecallBadge recallCase={recallCase} />}
        <dl className="grid grid-cols-2 gap-x-4 gap-y-3 rounded-xl border border-border-subtle bg-surface p-4 text-sm sm:grid-cols-3">
          <div>
            <dt className="text-xs font-medium uppercase tracking-wide text-ink-muted">Crop / Variety</dt>
            <dd className="text-ink">
              {lot.crop.common_name}
              {lot.variety ? ` / ${lot.variety.name}` : ""}
            </dd>
          </div>
          <div>
            <dt className="text-xs font-medium uppercase tracking-wide text-ink-muted">Exact grade</dt>
            <dd className="text-ink">{labels[lot.grade_definition_version_id] ?? lot.grade_definition_version_id}</dd>
          </div>
          <div>
            <dt className="text-xs font-medium uppercase tracking-wide text-ink-muted">Source Harvested Produce Lot</dt>
            <dd className="text-ink">
              {gradingEventQuery.data?.source_produce_lot_code ?? (gradingEventQuery.isLoading ? "Loading…" : "—")}
            </dd>
          </div>
          <div>
            {/* Immutable historical fact -- what this Lot originally
                received, distinct from what's still available now. */}
            <dt className="text-xs font-medium uppercase tracking-wide text-ink-muted">Original received</dt>
            <dd className="text-ink">
              {lot.original_received_weight_kg} kg
              {isCountMode ? ` / ${lot.original_received_whole_unit_count} units` : ""}
            </dd>
          </div>
          <div>
            {/* The authoritative, live current balance -- never the same
                number as Original received once any Packing has consumed
                from this Lot. */}
            <dt className="text-xs font-medium uppercase tracking-wide text-ink-muted">Current available</dt>
            <dd className="font-semibold text-ink">
              {balanceQuery.data
                ? `${balanceQuery.data.available_weight_kg} kg${
                    isCountMode ? ` / ${balanceQuery.data.available_whole_unit_count} units` : ""
                  }`
                : balanceQuery.isLoading
                  ? "Loading…"
                  : "—"}
            </dd>
          </div>
          <div>
            <dt className="text-xs font-medium uppercase tracking-wide text-ink-muted">Effective time</dt>
            <dd className="text-ink">{new Date(lot.effective_time).toLocaleString()}</dd>
          </div>
        </dl>

        <div>
          <h2 className="mb-2 font-serif text-sm font-semibold text-ink">Ledger</h2>
          {ledgerQuery.isLoading && <LoadingSkeleton rows={2} label="Loading ledger" />}
          {ledgerQuery.data && ledgerQuery.data.length === 0 && (
            <p className="text-sm text-ink-muted">No ledger entries yet.</p>
          )}
          {ledgerQuery.data && ledgerQuery.data.length > 0 && (
            <ul className="flex flex-col divide-y divide-border-subtle rounded-xl border border-border-subtle bg-surface text-sm">
              {ledgerQuery.data.map((entry) => (
                <li key={entry.id} className="flex flex-wrap items-center justify-between gap-2 p-3">
                  <span className="text-ink">{GPL_LEDGER_ENTRY_KIND_LABEL[entry.entry_kind] ?? entry.entry_kind}</span>
                  <span className="text-ink">
                    {Number(entry.weight_delta_kg) > 0 ? "+" : ""}
                    {entry.weight_delta_kg} kg
                    {entry.whole_unit_count_delta != null ? ` / ${entry.whole_unit_count_delta} units` : ""}
                  </span>
                  <span className="text-ink-muted">{new Date(entry.effective_time).toLocaleString()}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}
