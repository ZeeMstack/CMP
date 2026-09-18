"use client";

import Link from "next/link";
import { useMemo, useState } from "react";

import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { LoadingSkeleton } from "@/components/LoadingSkeleton";
import { RiskSignalBadge } from "@/components/planning/RiskSignalBadge";
import { tableBodyDividerClass, tableHeadRowClass, tableRowHoverClass, tableTdClass, tableThClass, tableWrapperClass } from "@/components/ui/table";
import type { BatchHarvestForecastStatusRead } from "@/lib/api/client";
import { formatPlacementSummary } from "@/lib/format/placement";
import { formatPlanDate } from "@/lib/format/planDate";
import { formatQuantity } from "@/lib/format/planQuantity";
import { useBatchHarvestForecastStatuses, useFarmHarvestForecastSummary, useOperationalSummary } from "@/lib/query/hooks";

const BASIS_LABEL: Record<string, string> = {
  grower_estimate: "Grower estimate",
  planning_assumption: "Planning assumption",
  protocol_guidance: "Protocol guidance",
};

type ForecastFilter = "all" | "has_forecast" | "no_forecast";

interface Row {
  batchId: string;
  batchCode: string;
  cropName: string;
  varietyName: string | null;
  stageName: string;
  locationSummary: string;
  status: BatchHarvestForecastStatusRead | undefined;
  hasForecast: boolean;
}

/** PILOT-PLAN-001B section 5: the farm-wide Harvest Forecast Worksheet.
 * `GET /harvest-forecast-summary` only ever returns Batches whose CURRENT
 * forecast window overlaps the selected period (see
 * docs/domain/HARVEST_FORECAST_CAPACITY_MODEL.md's Time Semantics), so a
 * Batch with a forecast outside the window is indistinguishable from one
 * with no forecast at all using that endpoint alone. To make the "no
 * forecast" filter truthful (never silently reclassifying an out-of-window
 * forecast as "none"), this cross-checks every active Batch's own current
 * forecast status directly. */
export function HarvestForecastWorksheetTable({
  farmId,
  periodStart,
  periodEnd,
}: {
  farmId: string;
  periodStart: string;
  periodEnd: string;
}) {
  const activeBatchesQuery = useOperationalSummary(farmId, "active");
  const summaryQuery = useFarmHarvestForecastSummary(farmId, periodStart, periodEnd);
  const activeBatchIds = useMemo(() => (activeBatchesQuery.data ?? []).map((b) => b.id), [activeBatchesQuery.data]);
  const statuses = useBatchHarvestForecastStatuses(farmId, activeBatchIds);

  const [cropFilter, setCropFilter] = useState("");
  const [varietyFilter, setVarietyFilter] = useState("");
  const [stageFilter, setStageFilter] = useState("");
  const [riskOnly, setRiskOnly] = useState(false);
  const [forecastFilter, setForecastFilter] = useState<ForecastFilter>("all");

  if (activeBatchesQuery.isLoading || summaryQuery.isLoading) {
    return <LoadingSkeleton rows={5} label="Loading harvest forecast worksheet" />;
  }
  if (activeBatchesQuery.error) {
    return <ErrorState error={activeBatchesQuery.error} onRetry={() => activeBatchesQuery.refetch()} />;
  }
  if (summaryQuery.error) {
    return <ErrorState error={summaryQuery.error} onRetry={() => summaryQuery.refetch()} />;
  }

  const inWindowStatusByBatchId = new Map((summaryQuery.data ?? []).map((s) => [s.batch_id, s]));

  const rows: Row[] = (activeBatchesQuery.data ?? []).map((batch) => {
    const inWindow = inWindowStatusByBatchId.get(batch.id);
    const fullStatus = statuses.byBatchId[batch.id];
    return {
      batchId: batch.id,
      batchCode: batch.code,
      cropName: batch.crop.common_name,
      varietyName: batch.variety?.name ?? null,
      stageName: batch.current_stage.name,
      locationSummary: formatPlacementSummary(batch.placement),
      status: inWindow,
      hasForecast: Boolean(fullStatus?.current_forecast) || Boolean(inWindow?.current_forecast),
    };
  });

  const crops = [...new Set(rows.map((r) => r.cropName))].sort();
  const varieties = [...new Set(rows.map((r) => r.varietyName).filter((v): v is string => Boolean(v)))].sort();
  const stages = [...new Set(rows.map((r) => r.stageName))].sort();

  const filtered = rows.filter((row) => {
    if (cropFilter && row.cropName !== cropFilter) return false;
    if (varietyFilter && row.varietyName !== varietyFilter) return false;
    if (stageFilter && row.stageName !== stageFilter) return false;
    if (riskOnly && !(row.status && row.status.open_crop_issue_count > 0)) return false;
    if (forecastFilter === "has_forecast" && !row.hasForecast) return false;
    if (forecastFilter === "no_forecast" && row.hasForecast) return false;
    // Default "all": show every in-window forecasted Batch, plus every
    // Batch confirmed (via the bulk status fan-out) to have no forecast at
    // all -- never a Batch whose forecast merely falls outside the window,
    // which would misreport an out-of-window forecast as "no forecast".
    if (forecastFilter === "all" && !row.status && row.hasForecast) return false;
    return true;
  });

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <select value={cropFilter} onChange={(e) => setCropFilter(e.target.value)} className="min-h-9 rounded-md border border-wl-border bg-wl-surface px-2 text-sm text-wl-text">
          <option value="">All crops</option>
          {crops.map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
        <select value={varietyFilter} onChange={(e) => setVarietyFilter(e.target.value)} className="min-h-9 rounded-md border border-wl-border bg-wl-surface px-2 text-sm text-wl-text">
          <option value="">All varieties</option>
          {varieties.map((v) => <option key={v} value={v}>{v}</option>)}
        </select>
        <select value={stageFilter} onChange={(e) => setStageFilter(e.target.value)} className="min-h-9 rounded-md border border-wl-border bg-wl-surface px-2 text-sm text-wl-text">
          <option value="">All stages</option>
          {stages.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
        <select
          value={forecastFilter}
          onChange={(e) => setForecastFilter(e.target.value as ForecastFilter)}
          className="min-h-9 rounded-md border border-wl-border bg-wl-surface px-2 text-sm text-wl-text"
        >
          <option value="all">All</option>
          <option value="has_forecast">Has forecast (in window)</option>
          <option value="no_forecast">No forecast</option>
        </select>
        <label className="flex min-h-9 items-center gap-1.5 text-sm text-wl-text">
          <input type="checkbox" checked={riskOnly} onChange={(e) => setRiskOnly(e.target.checked)} />
          Risk only
        </label>
      </div>

      {filtered.length === 0 ? (
        <EmptyState title="No batches match this worksheet's filters." description="Adjust the period or filters above." />
      ) : (
        <div className={tableWrapperClass}>
          <table className="w-full min-w-[1100px] text-left text-sm">
            <thead className={tableHeadRowClass}>
              <tr>
                <th scope="col" className={tableThClass}>Batch</th>
                <th scope="col" className={tableThClass}>Crop</th>
                <th scope="col" className={tableThClass}>Variety</th>
                <th scope="col" className={tableThClass}>Stage</th>
                <th scope="col" className={tableThClass}>Location</th>
                <th scope="col" className={tableThClass}>Window</th>
                <th scope="col" className={tableThClass}>Low</th>
                <th scope="col" className={tableThClass}>Expected</th>
                <th scope="col" className={tableThClass}>High</th>
                <th scope="col" className={tableThClass}>Harvested to date</th>
                <th scope="col" className={tableThClass}>Remaining</th>
                <th scope="col" className={tableThClass}>Risk</th>
                <th scope="col" className={tableThClass}>Basis</th>
                <th scope="col" className={tableThClass}>Last revised</th>
              </tr>
            </thead>
            <tbody className={tableBodyDividerClass}>
              {filtered.map((row) => {
                const forecast = row.status?.current_forecast;
                return (
                  <tr key={row.batchId} className={tableRowHoverClass}>
                    <td className={`${tableTdClass} whitespace-nowrap`}>
                      <Link href={`/farms/${farmId}/crop-batches/${row.batchId}?tab=forecast`} className="font-medium text-wl-brand hover:underline">
                        {row.batchCode}
                      </Link>
                    </td>
                    <td className={tableTdClass}>{row.cropName}</td>
                    <td className={`${tableTdClass} text-wl-text-secondary`}>{row.varietyName ?? "—"}</td>
                    <td className={tableTdClass}>{row.stageName}</td>
                    <td className={`${tableTdClass} text-wl-text-secondary`}>{row.locationSummary}</td>
                    {forecast ? (
                      <>
                        <td className={`${tableTdClass} whitespace-nowrap`}>
                          {formatPlanDate(forecast.window_start_date)} – {formatPlanDate(forecast.window_end_date)}
                        </td>
                        <td className={`${tableTdClass} whitespace-nowrap`}>{formatQuantity(forecast.low_quantity, forecast.uom.code)}</td>
                        <td className={`${tableTdClass} whitespace-nowrap font-medium`}>{formatQuantity(forecast.expected_quantity, forecast.uom.code)}</td>
                        <td className={`${tableTdClass} whitespace-nowrap`}>{formatQuantity(forecast.high_quantity, forecast.uom.code)}</td>
                        <td className={`${tableTdClass} whitespace-nowrap`}>
                          {row.status?.actual.comparable_to_forecast_uom
                            ? formatQuantity(row.status.actual.actual_quantity_in_forecast_uom ?? "0", forecast.uom.code)
                            : `${row.status?.actual.total_harvested_weight_kg ?? "0"} kg (not comparable)`}
                        </td>
                        <td className={`${tableTdClass} whitespace-nowrap`}>
                          {row.status?.actual.comparable_to_forecast_uom
                            ? formatQuantity(row.status.actual.remaining_forecast_quantity_in_forecast_uom ?? "0", forecast.uom.code)
                            : "—"}
                        </td>
                        <td className={tableTdClass}>
                          <RiskSignalBadge farmId={farmId} batchId={row.batchId} openCropIssueCount={row.status?.open_crop_issue_count ?? 0} />
                        </td>
                        <td className={`${tableTdClass} text-wl-text-secondary`}>{BASIS_LABEL[forecast.basis] ?? forecast.basis}</td>
                        <td className={`${tableTdClass} whitespace-nowrap text-wl-text-secondary`}>
                          {new Date(forecast.recorded_time).toLocaleDateString()}
                        </td>
                      </>
                    ) : (
                      <td className={tableTdClass} colSpan={9}>
                        <span className="text-wl-text-secondary">
                          {row.hasForecast ? "Forecast outside this period" : "No forecast recorded"}
                        </span>
                      </td>
                    )}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      {statuses.hasError && (
        <p className="text-xs text-wl-text-secondary">
          Some batches&apos; forecast status could not be confirmed -- the &quot;No forecast&quot; filter may be incomplete.
        </p>
      )}
    </div>
  );
}
