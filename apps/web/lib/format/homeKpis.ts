import type { BatchOperationalContext } from "@/lib/api/client";

/**
 * Pure Home-KPI computation, extracted from the page component so its
 * semantics can be unit-tested without mounting Next.js routing. Callers
 * must already have filtered to `state=active` batches (the operational-
 * summary route's own `state` param) -- this function does not re-filter
 * by state itself, so it can't silently mix in closed/superseded batches.
 */
export interface HomeKpis {
  activeCount: number;
  harvestReadyCount: number;
  openHoldBatchCount: number;
}

export function computeHomeKpis(activeBatches: BatchOperationalContext[]): HomeKpis {
  return {
    activeCount: activeBatches.length,
    // Authoritative stage_category, never inferred from stage name/code.
    harvestReadyCount: activeBatches.filter((b) => b.current_stage.stage_category === "harvest_ready").length,
    // Count of *batches* with at least one open hold, not a sum of
    // individual hold records.
    openHoldBatchCount: activeBatches.filter((b) => b.open_quality_hold_count > 0).length,
  };
}
