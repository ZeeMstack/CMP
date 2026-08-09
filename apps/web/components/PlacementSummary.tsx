import type { PlacementFacts } from "@/lib/api/client";
import { formatPlacementSummary } from "@/lib/format/placement";

/** Renders the backend's structured `PlacementFacts` as one truthful,
 * concise line of copy -- see lib/format/placement.ts for the exact rules
 * per case (unplaced, single, shared-branch, partial, scattered). */
export function PlacementSummary({ placement, className }: { placement: PlacementFacts; className?: string }) {
  return <span className={className}>{formatPlacementSummary(placement)}</span>;
}
