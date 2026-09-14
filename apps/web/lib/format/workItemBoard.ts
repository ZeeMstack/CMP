import type { FarmWorkItemRead } from "@/lib/api/client";

/**
 * Pure Today-on-the-Farm board bucketing, extracted from the page
 * component so its semantics can be unit-tested without mounting Next.js
 * routing -- mirrors `computeHomeKpis`/`groupBatchesByStage`'s established
 * pattern. Today on the Farm issues exactly ONE work-item list request
 * (non-terminal items only, `useWorkItems`); every section below is a
 * different lens over that same set, not a separate backend read, so a
 * row can legitimately appear in more than one section (e.g. an item that
 * is both mine and blocked).
 */

const ACTIVE_STATUSES = new Set(["open", "in_progress", "blocked"]);

/** Farm-local calendar date (YYYY-MM-DD) for an ISO instant, in the
 * farm's own IANA timezone -- never the browser's local zone and never a
 * naive UTC slice (CLAUDE.md "Time"). */
export function localDateKey(isoInstant: string, timeZone: string): string {
  const formatter = new Intl.DateTimeFormat("en-CA", { timeZone, year: "numeric", month: "2-digit", day: "2-digit" });
  return formatter.format(new Date(isoInstant));
}

/** The date a Work Item is "for", in the farm's own timezone -- due date
 * if set, otherwise its creation date (CLAUDE.md: "Derive [carryover]
 * from due/work dates and unresolved status where possible"). */
function workDateKey(item: FarmWorkItemRead, timeZone: string): string {
  return localDateKey(item.due_at ?? item.created_at, timeZone);
}

export interface WorkItemBoard {
  myWork: FarmWorkItemRead[];
  inProgress: FarmWorkItemRead[];
  blocked: FarmWorkItemRead[];
  carryover: FarmWorkItemRead[];
  /** Every non-terminal item, farm-wide -- shown to roles with broader
   * visibility as "Farm Work" (see docs/product/PRODUCT_SCOPE.md's Farm
   * Work Item note). Never filtered down further here; a role without
   * `farm_work_item.manage` simply sees the same list operators do. */
  farmWide: FarmWorkItemRead[];
}

export function bucketWorkItems(
  items: FarmWorkItemRead[],
  options: { currentUserId?: string; now: Date; farmTimezone: string },
): WorkItemBoard {
  const { currentUserId, now, farmTimezone } = options;
  const active = items.filter((i) => ACTIVE_STATUSES.has(i.status));
  const todayKey = localDateKey(now.toISOString(), farmTimezone);

  return {
    myWork: currentUserId ? active.filter((i) => i.assigned_to_user_id === currentUserId) : [],
    inProgress: active.filter((i) => i.status === "in_progress"),
    blocked: active.filter((i) => i.status === "blocked"),
    carryover: active.filter((i) => workDateKey(i, farmTimezone) < todayKey),
    farmWide: active,
  };
}
