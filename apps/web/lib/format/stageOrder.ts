/**
 * The backend's own authoritative stage-category progression (mirrors
 * `STAGE_CATEGORIES` in apps/api/app/models/workflow_stage.py -- a fixed
 * domain concept, not pilot-specific data). `OperationalStageSummary`
 * does not expose a per-stage `display_order`, so true cross-workflow
 * workflow ordering cannot be proven here; this category order is the
 * best deterministic, biologically-meaningful grouping available without
 * inventing a sequence. Stages sharing a category (no finer signal being
 * available) are ordered alphabetically by name as a documented,
 * deterministic tiebreak -- not a claim of true workflow sequence.
 */
const STAGE_CATEGORY_ORDER = [
  "seeding",
  "germination",
  "nursery",
  "transplanting",
  "intermediate",
  "production",
  "harvest_ready",
  "harvesting",
  "completed",
  "rejected",
] as const;

function categoryRank(category: string): number {
  const index = STAGE_CATEGORY_ORDER.indexOf(category as (typeof STAGE_CATEGORY_ORDER)[number]);
  return index === -1 ? STAGE_CATEGORY_ORDER.length : index;
}

export function compareStageGroups(
  a: { category: string; name: string },
  b: { category: string; name: string },
): number {
  const rankDiff = categoryRank(a.category) - categoryRank(b.category);
  if (rankDiff !== 0) return rankDiff;
  return a.name.localeCompare(b.name);
}

export interface StageGroup {
  category: string;
  name: string;
  count: number;
}

/**
 * Groups batches by (stage_category, stage name) -- never by stage ID
 * alone (which would fragment equivalent configured workflows into
 * separate rows for no operational reason) and never by name alone
 * (which would silently merge two genuinely different stages -- e.g. a
 * nursery "Growing" step and a production "Growing" step -- that only
 * happen to share a display name). `stage_category` is always read from
 * the batch's own authoritative field, never inferred from name/code.
 */
export function groupBatchesByStage(
  batches: { current_stage: { name: string; stage_category: string } }[],
): StageGroup[] {
  const groups = new Map<string, StageGroup>();
  for (const batch of batches) {
    const { name, stage_category: category } = batch.current_stage;
    // Space-separated composite key -- collision-proof in practice since
    // `stage_category` is a fixed backend enum with no spaces.
    const key = `${category} ${name}`;
    const existing = groups.get(key);
    if (existing) {
      existing.count += 1;
    } else {
      groups.set(key, { category, name, count: 1 });
    }
  }
  return [...groups.values()].sort(compareStageGroups);
}
