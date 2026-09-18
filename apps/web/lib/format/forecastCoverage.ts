import type { RequirementHarvestOutlook } from "@/lib/api/client";

/** PILOT-PLAN-001B: the Requirement Coverage worksheet's explicit states.
 * Never a percentage, never a color-only meaning -- `RequirementHarvestOutlook`
 * itself carries no enum status (see docs/domain/HARVEST_FORECAST_CAPACITY_MODEL.md
 * Part 7), so this derives one, purely from its quantity/boolean fields, and
 * never invents a conversion the backend didn't already resolve. */
export type CoverageStatus = "SHORT" | "COVERED" | "OVER" | "NOT_COMPARABLE" | "NO_FORECAST";

export const COVERAGE_STATUS_LABEL: Record<CoverageStatus, string> = {
  SHORT: "Short",
  COVERED: "Covered",
  OVER: "Over",
  NOT_COMPARABLE: "Not comparable",
  NO_FORECAST: "No forecast",
};

export function deriveCoverageStatus(outlook: RequirementHarvestOutlook | undefined): CoverageStatus {
  if (!outlook) return "NO_FORECAST";
  if (outlook.batches_with_current_forecast_count === 0) return "NO_FORECAST";
  if (!outlook.forecast_comparable || outlook.coverage_gap_quantity === null) return "NOT_COMPARABLE";
  const gap = Number(outlook.coverage_gap_quantity);
  if (!Number.isFinite(gap)) return "NOT_COMPARABLE";
  if (gap > 0) return "SHORT";
  if (gap < 0) return "OVER";
  return "COVERED";
}
