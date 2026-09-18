"use client";

import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { LoadingSkeleton } from "@/components/LoadingSkeleton";
import { tableBodyDividerClass, tableHeadRowClass, tableRowHoverClass, tableTdClass, tableThClass, tableWrapperClass } from "@/components/ui/table";
import { buildForecastTimeline } from "@/lib/format/forecastTimeline";
import { formatPlanDate } from "@/lib/format/planDate";
import { formatQuantity } from "@/lib/format/planQuantity";
import { useFarmHarvestForecastSummary } from "@/lib/query/hooks";

/** PILOT-PLAN-001B section 6: "what is expected to become harvestable each
 * week" -- a plain grouped table, never a Gantt/chart library. Rows are
 * grouped by (week, forecast UOM) -- see `buildForecastTimeline`'s own
 * comment for why quantities are never summed across different UOMs. This
 * is a range, not a confirmed number: it never implies more precision than
 * the recorded Low/Expected/High. */
export function HarvestForecastTimeline({
  farmId,
  periodStart,
  periodEnd,
}: {
  farmId: string;
  periodStart: string;
  periodEnd: string;
}) {
  const summaryQuery = useFarmHarvestForecastSummary(farmId, periodStart, periodEnd);

  if (summaryQuery.isLoading) return <LoadingSkeleton rows={4} label="Loading forecast timeline" />;
  if (summaryQuery.error) return <ErrorState error={summaryQuery.error} onRetry={() => summaryQuery.refetch()} />;

  const rows = buildForecastTimeline(summaryQuery.data ?? []);
  if (rows.length === 0) {
    return <EmptyState title="No forecasted batches in this period." description="Adjust the planning period above." />;
  }

  return (
    <div className={tableWrapperClass}>
      <table className="w-full min-w-[640px] text-left text-sm">
        <thead className={tableHeadRowClass}>
          <tr>
            <th scope="col" className={tableThClass}>Week of</th>
            <th scope="col" className={tableThClass}>Unit</th>
            <th scope="col" className={tableThClass}>Low</th>
            <th scope="col" className={tableThClass}>Expected</th>
            <th scope="col" className={tableThClass}>High</th>
            <th scope="col" className={tableThClass}>Actual harvested</th>
            <th scope="col" className={tableThClass}>Batches</th>
          </tr>
        </thead>
        <tbody className={tableBodyDividerClass}>
          {rows.map((row) => (
            <tr key={`${row.weekStart}__${row.uomCode}`} className={tableRowHoverClass}>
              <td className={`${tableTdClass} whitespace-nowrap`}>{formatPlanDate(row.weekStart)}</td>
              <td className={tableTdClass}>{row.uomCode}</td>
              <td className={`${tableTdClass} whitespace-nowrap`}>{formatQuantity(String(row.lowQuantity), row.uomCode)}</td>
              <td className={`${tableTdClass} whitespace-nowrap font-medium`}>{formatQuantity(String(row.expectedQuantity), row.uomCode)}</td>
              <td className={`${tableTdClass} whitespace-nowrap`}>{formatQuantity(String(row.highQuantity), row.uomCode)}</td>
              <td className={`${tableTdClass} whitespace-nowrap`}>
                {row.actualHarvestedQuantity === null
                  ? "—"
                  : `${formatQuantity(String(row.actualHarvestedQuantity), row.uomCode)}${row.comparableBatchCount < row.batchCount ? ` (${row.comparableBatchCount}/${row.batchCount} batches)` : ""}`}
              </td>
              <td className={tableTdClass}>{row.batchCount}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
