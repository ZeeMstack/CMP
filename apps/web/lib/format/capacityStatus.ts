import type { LocationCapacitySummaryRead } from "@/lib/api/client";

/** PILOT-PLAN-001B: the Capacity Outlook worksheet's explicit states. The
 * backend only ever returns `capacity_status: "known" | "unknown"` (see
 * docs/domain/HARVEST_FORECAST_CAPACITY_MODEL.md Part 4/6) -- this derives
 * the richer worksheet status purely from `authoritative_capacity`/
 * `planned_used_capacity`/`available_planned_capacity`, never fabricating a
 * number the backend didn't compute. UNKNOWN is never shown as "Unlimited". */
export type CapacityStatus = "AVAILABLE" | "FULL" | "OVER_COMMITTED" | "UNKNOWN" | "NO_ALLOCATION";

export const CAPACITY_STATUS_LABEL: Record<CapacityStatus, string> = {
  AVAILABLE: "Available",
  FULL: "Full",
  OVER_COMMITTED: "Over-committed",
  UNKNOWN: "Unknown capacity",
  NO_ALLOCATION: "No allocation",
};

export function deriveCapacityStatus(summary: LocationCapacitySummaryRead | undefined): CapacityStatus {
  if (!summary) return "UNKNOWN";
  if (summary.capacity_status === "unknown" || summary.available_planned_capacity === null) return "UNKNOWN";
  if (summary.planned_used_capacity === 0) return "NO_ALLOCATION";
  if (summary.available_planned_capacity < 0) return "OVER_COMMITTED";
  if (summary.available_planned_capacity === 0) return "FULL";
  return "AVAILABLE";
}
