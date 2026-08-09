import type { LocationPathSegment, PlacementFacts } from "@/lib/api/client";

/**
 * Turns the backend's structured `PlacementFacts` into truthful, concise
 * operator copy. The backend deliberately returns only facts (counts,
 * paths, IDs) -- every string here is frontend-owned. Never hides an
 * unplaced active carrier, never picks one placement out of several and
 * calls it "the" location, never infers plant quantity from carrier/
 * placement counts.
 */

/** First two named ancestor levels, e.g. "Greenhouse 01 / Zone A" -- never
 * the full technical leaf path by default (see PlacementSummary's detail
 * view for that). */
function conciseAncestorLabel(segments: readonly Pick<LocationPathSegment, "name">[]): string {
  return segments
    .slice(0, 2)
    .map((segment) => segment.name)
    .join(" / ");
}

export function formatPlacementSummary(placement: PlacementFacts): string {
  const { active_carrier_count, placed_carrier_count, unplaced_carrier_count, placements, common_ancestor_path } =
    placement;

  if (active_carrier_count === 0) return "No current carriers";
  if (placed_carrier_count === 0) return "Not yet placed";

  const unplacedSuffix = unplaced_carrier_count > 0 ? ` · ${unplaced_carrier_count} unplaced` : "";

  if (placed_carrier_count === 1) {
    const [only] = placements;
    return `${conciseAncestorLabel(only.path)}${unplacedSuffix}`;
  }

  if (common_ancestor_path && common_ancestor_path.length > 0) {
    return `${conciseAncestorLabel(common_ancestor_path)} · ${placed_carrier_count} locations${unplacedSuffix}`;
  }

  const branchCount = new Set(placements.map((p) => p.path[0]?.id).filter((id): id is string => Boolean(id))).size;
  return `${placed_carrier_count} locations across ${branchCount} branches${unplacedSuffix}`;
}
