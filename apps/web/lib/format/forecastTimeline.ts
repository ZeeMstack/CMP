import type { BatchHarvestForecastStatusRead } from "@/lib/api/client";

/** PILOT-PLAN-001B: "what is expected to become harvestable each week" --
 * a lightweight grouping, never a Gantt/chart library. Each Batch's current
 * forecast is bucketed into the ISO week containing its `window_start_date`.
 *
 * Batches are never summed across different UOMs (a Low/Expected/High in
 * `kg` and one in `EA` cannot be added without an invented conversion --
 * see CLAUDE.md rule 8 and docs/product/OPEN-QUESTIONS.md's "no invented
 * conversion" decisions) -- so each row is keyed by (week, UOM code), and a
 * week with multiple forecast UOMs in play simply renders as multiple rows
 * for that week. */
export interface ForecastTimelineRow {
  weekStart: string;
  uomCode: string;
  batchCount: number;
  lowQuantity: number;
  expectedQuantity: number;
  highQuantity: number;
  /** Sum of `actual.actual_quantity_in_forecast_uom` across batches in this
   * week+UOM group whose actual harvest is comparable to their forecast
   * UOM. `null` when none of the batches in the group are comparable --
   * never fabricated as zero, which would misreport "nothing harvested yet"
   * as "confirmed zero harvested". */
  actualHarvestedQuantity: number | null;
  comparableBatchCount: number;
}

function isoWeekStart(isoDate: string): string {
  const [year, month, day] = isoDate.split("-").map(Number);
  const date = new Date(Date.UTC(year, month - 1, day));
  // ISO week starts Monday: getUTCDay() 0=Sun..6=Sat, shift so Monday=0.
  const weekday = (date.getUTCDay() + 6) % 7;
  date.setUTCDate(date.getUTCDate() - weekday);
  return date.toISOString().slice(0, 10);
}

export function buildForecastTimeline(batches: BatchHarvestForecastStatusRead[]): ForecastTimelineRow[] {
  const groups = new Map<string, ForecastTimelineRow>();

  for (const batch of batches) {
    const forecast = batch.current_forecast;
    if (!forecast) continue;
    const weekStart = isoWeekStart(forecast.window_start_date);
    const key = `${weekStart}__${forecast.uom.code}`;
    const existing = groups.get(key) ?? {
      weekStart,
      uomCode: forecast.uom.code,
      batchCount: 0,
      lowQuantity: 0,
      expectedQuantity: 0,
      highQuantity: 0,
      actualHarvestedQuantity: null,
      comparableBatchCount: 0,
    };
    existing.batchCount += 1;
    existing.lowQuantity += Number(forecast.low_quantity);
    existing.expectedQuantity += Number(forecast.expected_quantity);
    existing.highQuantity += Number(forecast.high_quantity);
    if (batch.actual.comparable_to_forecast_uom && batch.actual.actual_quantity_in_forecast_uom !== null) {
      existing.actualHarvestedQuantity =
        (existing.actualHarvestedQuantity ?? 0) + Number(batch.actual.actual_quantity_in_forecast_uom);
      existing.comparableBatchCount += 1;
    }
    groups.set(key, existing);
  }

  return [...groups.values()].sort((a, b) =>
    a.weekStart === b.weekStart ? a.uomCode.localeCompare(b.uomCode) : a.weekStart.localeCompare(b.weekStart),
  );
}
