import type { EquipmentReadinessStateRead } from "@/lib/api/client";

/**
 * UX-OPS-001B: the single, shared source of truth for which readiness
 * commands are valid for a given `EquipmentReadinessStateRead`, reused by
 * both the Readiness queue's inspector and the Readiness detail page so
 * the two views can never drift into showing different actions for the
 * same entity. Mirrors docs/domain/EQUIPMENT_READINESS_MODEL.md's frozen
 * allowed-transitions table (PART 6) and ready-validation rules (PART 7)
 * exactly -- this is UI defense-in-depth only; the backend remains the
 * authoritative enforcement point (a 409 is still possible if state
 * changed after this page loaded). Never a duplicated persisted
 * transition table -- computed fresh from the server-owned facts on the
 * read (`requires_cleaning`, `is_in_use`, `latest_cleaning_result`) every
 * time, so it can never drift from what the backend would actually allow
 * (only from a state the client hasn't re-fetched yet, which is the
 * ordinary read-then-write staleness window every UI has).
 */

export type ReadinessAction =
  | "mark_awaiting_cleaning"
  | "record_cleaning"
  | "mark_ready"
  | "report_damage"
  | "send_to_maintenance"
  | "return_from_maintenance"
  | "retire";

export const READINESS_ACTION_LABEL: Record<ReadinessAction, string> = {
  mark_awaiting_cleaning: "Mark Awaiting Cleaning",
  record_cleaning: "Record Cleaning",
  mark_ready: "Mark Ready",
  report_damage: "Report Damage",
  send_to_maintenance: "Send to Maintenance",
  return_from_maintenance: "Return from Maintenance",
  retire: "Retire",
};

/** Every command a Carrier/Asset in this exact state may currently attempt,
 * in display order (forward-progressing commands first, exceptional
 * commands last). Empty for `retired` (terminal, no further action). */
export function computeAvailableReadinessActions(state: EquipmentReadinessStateRead): ReadinessAction[] {
  const s = state.current_state;
  if (s === "retired") return [];
  if (s === "damaged") return ["send_to_maintenance", "retire"];
  if (s === "maintenance") return ["return_from_maintenance", "report_damage", "retire"];

  // Carrier in-use blocks Mark Ready specifically (PART 7) -- never derived
  // for an Asset, which has no authoritative in-use signal (`is_in_use` is
  // `null`, not `false`, so it never participates in this check).
  const blockedByActiveAssignment = state.entity_type === "carrier" && state.is_in_use === true;

  const forward: ReadinessAction[] = [];
  if (s === "unknown") {
    // Frozen rule: a cleaning-required type can NEVER go directly
    // UNKNOWN -> READY -- it must pass through AWAITING_CLEANING first.
    if (state.requires_cleaning) forward.push("mark_awaiting_cleaning");
    else if (!blockedByActiveAssignment) forward.push("mark_ready");
  } else if (s === "awaiting_cleaning") {
    forward.push("record_cleaning");
  } else if (s === "cleaning_completed") {
    // Frozen rule: NEEDS_REWORK never offers Mark Ready -- only a most
    // recent COMPLETED cleaning result does.
    if (state.latest_cleaning_result === "completed" && !blockedByActiveAssignment) forward.push("mark_ready");
    // Always available from CLEANING_COMPLETED (re-clean path), including
    // to recover from a NEEDS_REWORK result -- PART 6's allowed-transitions
    // table lists CLEANING_COMPLETED -> AWAITING_CLEANING unconditionally.
    forward.push("mark_awaiting_cleaning");
  } else if (s === "ready" && state.requires_cleaning) {
    forward.push("mark_awaiting_cleaning");
  }

  return [...forward, "report_damage", "send_to_maintenance", "retire"];
}

/** The one primary, forward-progressing action for this state (never
 * `report_damage`/`send_to_maintenance`/`retire`, which stay secondary/
 * exceptional per ticket §7.5) -- `null` when there is none (e.g. already
 * `ready`, or blocked by an active Carrier assignment). */
export function primaryReadinessAction(state: EquipmentReadinessStateRead): ReadinessAction | null {
  const forwardKinds: ReadinessAction[] = ["mark_awaiting_cleaning", "record_cleaning", "mark_ready", "return_from_maintenance"];
  return computeAvailableReadinessActions(state).find((a) => forwardKinds.includes(a)) ?? null;
}
