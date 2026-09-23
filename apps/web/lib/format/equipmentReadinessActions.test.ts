import { describe, expect, it } from "vitest";

import type { ReadinessAction } from "@/lib/api/client";

import { READINESS_ACTION_LABEL } from "./equipmentReadinessActions";

// UX-OPS-001B R1 (blocker #3): the frozen-lifecycle-rules coverage that
// used to live here now lives against the real backend command behavior in
// apps/api/tests/test_equipment_readiness_actions.py (computed
// `available_actions`/`primary_action` are asserted to agree with what the
// actual transition commands accept/reject, per state) -- this file is a
// label map now, so it only needs to confirm the map is complete.
const ALL_ACTIONS: ReadinessAction[] = [
  "mark_awaiting_cleaning", "record_cleaning", "mark_ready", "report_damage",
  "send_to_maintenance", "return_from_maintenance", "retire",
];

describe("READINESS_ACTION_LABEL", () => {
  it("has a non-empty label for every ReadinessAction", () => {
    for (const action of ALL_ACTIONS) {
      expect(READINESS_ACTION_LABEL[action]).toBeTruthy();
    }
  });
});
