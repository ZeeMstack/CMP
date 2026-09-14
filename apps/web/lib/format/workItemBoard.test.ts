import { describe, expect, it } from "vitest";

import type { FarmWorkItemRead } from "@/lib/api/client";

import { bucketWorkItems, localDateKey } from "./workItemBoard";

function makeItem(overrides: Partial<FarmWorkItemRead> = {}): FarmWorkItemRead {
  return {
    id: "wi-1",
    tenant_id: "t1",
    farm_id: "f1",
    code: "FW-20260914-0001",
    work_type: "cleaning",
    category: "cleaning",
    title: "Clean Trolley",
    instructions: null,
    status: "open",
    priority: "normal",
    due_at: null,
    assigned_to_user_id: null,
    crop_batch: null,
    location: null,
    carrier: null,
    asset: null,
    quantity: null,
    quantity_uom: null,
    completion_mode: "manual_record",
    result_entity_type: null,
    result_entity_id: null,
    result_recorded_at: null,
    completed_by_user_id: null,
    completed_at: null,
    completion_note: null,
    blocked_reason: null,
    blocked_at: null,
    blocked_by_user_id: null,
    cancelled_at: null,
    cancelled_by_user_id: null,
    cancel_reason: null,
    created_by_user_id: "u1",
    created_at: "2026-09-14T06:00:00Z",
    updated_at: "2026-09-14T06:00:00Z",
    ...overrides,
  };
}

const FARM_TZ = "Asia/Dubai"; // UTC+4
const NOW = new Date("2026-09-14T10:00:00Z"); // 2026-09-14 14:00 Dubai time

describe("localDateKey", () => {
  it("resolves the farm's own timezone, not UTC or the browser's local zone", () => {
    // 2026-09-14T21:30:00Z is already 2026-09-15 01:30 in Dubai (UTC+4).
    expect(localDateKey("2026-09-14T21:30:00Z", FARM_TZ)).toBe("2026-09-15");
    expect(localDateKey("2026-09-14T21:30:00Z", "UTC")).toBe("2026-09-14");
  });
});

describe("bucketWorkItems", () => {
  it("puts items assigned to the current user into myWork, and excludes unassigned/other-user items", () => {
    const mine = makeItem({ id: "mine", assigned_to_user_id: "me" });
    const other = makeItem({ id: "other", assigned_to_user_id: "someone-else" });
    const unassigned = makeItem({ id: "unassigned" });
    const board = bucketWorkItems([mine, other, unassigned], { currentUserId: "me", now: NOW, farmTimezone: FARM_TZ });
    expect(board.myWork.map((i) => i.id)).toEqual(["mine"]);
  });

  it("returns no myWork items when no current user is known", () => {
    const board = bucketWorkItems([makeItem({ assigned_to_user_id: "me" })], { now: NOW, farmTimezone: FARM_TZ });
    expect(board.myWork).toEqual([]);
  });

  it("buckets in_progress and blocked independently of assignment", () => {
    const items = [
      makeItem({ id: "ip", status: "in_progress" }),
      makeItem({ id: "blocked", status: "blocked", blocked_reason: "destination full" }),
      makeItem({ id: "open", status: "open" }),
    ];
    const board = bucketWorkItems(items, { now: NOW, farmTimezone: FARM_TZ });
    expect(board.inProgress.map((i) => i.id)).toEqual(["ip"]);
    expect(board.blocked.map((i) => i.id)).toEqual(["blocked"]);
  });

  it("classifies carryover by due_at when set, falling back to created_at otherwise", () => {
    const yesterdayDue = makeItem({ id: "overdue", due_at: "2026-09-13T08:00:00Z" });
    const todayDue = makeItem({ id: "due-today", due_at: "2026-09-14T08:00:00Z" });
    const noDueOldCreation = makeItem({ id: "stale-open", due_at: null, created_at: "2026-09-10T08:00:00Z" });
    const noDueFreshCreation = makeItem({ id: "fresh-open", due_at: null, created_at: "2026-09-14T08:00:00Z" });

    const board = bucketWorkItems([yesterdayDue, todayDue, noDueOldCreation, noDueFreshCreation], {
      now: NOW,
      farmTimezone: FARM_TZ,
    });
    expect(board.carryover.map((i) => i.id).sort()).toEqual(["overdue", "stale-open"]);
  });

  it("excludes completed and cancelled items from every section", () => {
    const items = [
      makeItem({ id: "completed", status: "completed", completed_at: "2026-09-14T08:00:00Z" }),
      makeItem({ id: "cancelled", status: "cancelled", cancelled_at: "2026-09-14T08:00:00Z" }),
      makeItem({ id: "open", status: "open" }),
    ];
    const board = bucketWorkItems(items, { currentUserId: "me", now: NOW, farmTimezone: FARM_TZ });
    expect(board.farmWide.map((i) => i.id)).toEqual(["open"]);
  });

  it("farmWide includes every non-terminal item regardless of assignment", () => {
    const items = [
      makeItem({ id: "a", assigned_to_user_id: "me" }),
      makeItem({ id: "b", assigned_to_user_id: "someone-else" }),
      makeItem({ id: "c" }),
    ];
    const board = bucketWorkItems(items, { currentUserId: "me", now: NOW, farmTimezone: FARM_TZ });
    expect(board.farmWide.map((i) => i.id).sort()).toEqual(["a", "b", "c"]);
  });
});
