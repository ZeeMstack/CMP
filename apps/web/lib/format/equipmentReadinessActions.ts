import type { ReadinessAction } from "@/lib/api/client";

/**
 * UX-OPS-001B R1 (blocker #3): display labels only. Which actions are
 * available/primary for a given `EquipmentReadinessStateRead` is now
 * computed exactly once, backend-side, by
 * `equipment_readiness_service.compute_readiness_actions` and exposed as
 * `available_actions`/`primary_action` on the read itself -- this file
 * must never again reconstruct that transition table client-side (that
 * duplication is exactly what let the two drift; see
 * docs/domain/EQUIPMENT_READINESS_MODEL.md for the frozen source rules).
 */

export const READINESS_ACTION_LABEL: Record<ReadinessAction, string> = {
  mark_awaiting_cleaning: "Mark Awaiting Cleaning",
  record_cleaning: "Record Cleaning",
  mark_ready: "Mark Ready",
  report_damage: "Report Damage",
  send_to_maintenance: "Send to Maintenance",
  return_from_maintenance: "Return from Maintenance",
  retire: "Retire",
};
