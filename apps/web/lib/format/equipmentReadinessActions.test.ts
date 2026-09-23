import { describe, expect, it } from "vitest";

import type { EquipmentReadinessStateRead } from "@/lib/api/client";

import { computeAvailableReadinessActions, primaryReadinessAction } from "./equipmentReadinessActions";

function baseState(overrides: Partial<EquipmentReadinessStateRead> = {}): EquipmentReadinessStateRead {
  return {
    id: "state-1", tenant_id: "t1", farm_id: "f1", entity_type: "carrier",
    asset_id: null, carrier_id: "carrier-1", current_state: "unknown",
    state_changed_at: "2026-01-01T00:00:00Z", state_changed_by_user_id: null,
    state_note: null, last_cleaning_event_id: null,
    created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z",
    entity_code: "ST-0001", entity_name: null, equipment_type_code: "seed_tray", equipment_type_name: "Seed Tray",
    requires_cleaning: true, is_in_use: false, latest_cleaning_result: null,
    ...overrides,
  };
}

describe("computeAvailableReadinessActions: frozen lifecycle rules", () => {
  it("cleaning-required UNKNOWN never offers Mark Ready", () => {
    const actions = computeAvailableReadinessActions(baseState({ current_state: "unknown", requires_cleaning: true }));
    expect(actions).not.toContain("mark_ready");
    expect(actions).toContain("mark_awaiting_cleaning");
  });

  it("non-cleaning UNKNOWN can expose Mark Ready when otherwise valid", () => {
    const actions = computeAvailableReadinessActions(
      baseState({ current_state: "unknown", requires_cleaning: false, entity_type: "asset", asset_id: "asset-1", carrier_id: null, is_in_use: null }),
    );
    expect(actions).toContain("mark_ready");
    expect(actions).not.toContain("mark_awaiting_cleaning");
  });

  it("non-cleaning UNKNOWN Carrier blocked by an active assignment does not offer Mark Ready", () => {
    const actions = computeAvailableReadinessActions(
      baseState({ current_state: "unknown", requires_cleaning: false, is_in_use: true }),
    );
    expect(actions).not.toContain("mark_ready");
  });

  it("CLEANING_COMPLETED with latest result NEEDS_REWORK never offers Mark Ready", () => {
    const actions = computeAvailableReadinessActions(
      baseState({ current_state: "cleaning_completed", latest_cleaning_result: "needs_rework" }),
    );
    expect(actions).not.toContain("mark_ready");
    // The recovery path stays available.
    expect(actions).toContain("mark_awaiting_cleaning");
  });

  it("CLEANING_COMPLETED with latest result COMPLETED offers Mark Ready when not blocked by in-use", () => {
    const actions = computeAvailableReadinessActions(
      baseState({ current_state: "cleaning_completed", latest_cleaning_result: "completed", is_in_use: false }),
    );
    expect(actions).toContain("mark_ready");
  });

  it("CLEANING_COMPLETED with latest result COMPLETED but an active Carrier assignment still blocks Mark Ready", () => {
    const actions = computeAvailableReadinessActions(
      baseState({ current_state: "cleaning_completed", latest_cleaning_result: "completed", is_in_use: true }),
    );
    expect(actions).not.toContain("mark_ready");
  });

  it("READY for a non-cleaning type offers no Mark Awaiting Cleaning", () => {
    const actions = computeAvailableReadinessActions(baseState({ current_state: "ready", requires_cleaning: false }));
    expect(actions).not.toContain("mark_awaiting_cleaning");
  });

  it("READY for a cleaning-required type offers Mark Awaiting Cleaning", () => {
    const actions = computeAvailableReadinessActions(baseState({ current_state: "ready", requires_cleaning: true }));
    expect(actions).toContain("mark_awaiting_cleaning");
  });

  it("DAMAGED offers only Send to Maintenance and Retire", () => {
    expect(computeAvailableReadinessActions(baseState({ current_state: "damaged" }))).toEqual([
      "send_to_maintenance", "retire",
    ]);
  });

  it("MAINTENANCE offers Return from Maintenance, Report Damage, and Retire", () => {
    expect(computeAvailableReadinessActions(baseState({ current_state: "maintenance" }))).toEqual([
      "return_from_maintenance", "report_damage", "retire",
    ]);
  });

  it("RETIRED is terminal -- no actions at all", () => {
    expect(computeAvailableReadinessActions(baseState({ current_state: "retired" }))).toEqual([]);
  });

  it("AWAITING_CLEANING offers Record Cleaning", () => {
    const actions = computeAvailableReadinessActions(baseState({ current_state: "awaiting_cleaning" }));
    expect(actions).toContain("record_cleaning");
    expect(actions).not.toContain("mark_ready");
  });
});

describe("primaryReadinessAction", () => {
  it("is null for RETIRED", () => {
    expect(primaryReadinessAction(baseState({ current_state: "retired" }))).toBeNull();
  });

  it("is never report_damage/send_to_maintenance/retire", () => {
    const action = primaryReadinessAction(baseState({ current_state: "unknown", requires_cleaning: true }));
    expect(action).toBe("mark_awaiting_cleaning");
  });

  it("falls back to the re-clean path when Mark Ready is blocked by an active Carrier assignment", () => {
    const action = primaryReadinessAction(
      baseState({ current_state: "cleaning_completed", latest_cleaning_result: "completed", is_in_use: true }),
    );
    expect(action).toBe("mark_awaiting_cleaning");
  });
});
