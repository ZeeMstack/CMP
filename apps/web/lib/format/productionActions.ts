/** UX-OPS-001C: which Production inspector actions are currently valid for a
 * selected row, derived ONLY from server-owned facts already on the read
 * model (living population, current location, assignment identity) --
 * never from a crop, stage, greenhouse, or variety name, and never a
 * second lifecycle policy. The backend still enforces every command
 * authoritatively; this only avoids offering an action the server facts
 * already prove cannot succeed (e.g. moving a Plate with no recorded
 * location, or recording loss on zero living plants). */

export type ProductionActionKind = "move" | "record_loss" | "record_observation" | "inspect_crop" | "reprint_label";

export interface ProductionAction {
  kind: ProductionActionKind;
  label: string;
  /** Present for navigation actions (observation/inspection/label) --
   * absent for in-page command forms (move/loss). */
  href?: string;
}

export interface LeafyPlateFacts {
  batch_id: string;
  batch_carrier_assignment_id: string;
  current_living_population: number;
  current_location: unknown | null;
}

/** Leafy Production Plate (one active Batch Carrier Assignment). Order is
 * the inspector's display order; the first entry is the primary action. */
export function leafyPlateActions(farmId: string, plate: LeafyPlateFacts): ProductionAction[] {
  const actions: ProductionAction[] = [];
  const hasLiving = plate.current_living_population > 0;
  if (hasLiving) actions.push({ kind: "record_loss", label: "Record Plant Loss" });
  if (hasLiving && plate.current_location) actions.push({ kind: "move", label: "Move plate" });
  actions.push(...placementNavigationActions(farmId, plate.batch_id, plate.batch_carrier_assignment_id, hasLiving));
  return actions;
}

export interface VinesGrowBagFacts {
  batch_carrier_assignment_id: string;
  living_plant_count: number;
}

/** One Vines Grow Bag placement inside a selected (Batch, Gutter) group.
 * No Move: no Vines relocation command exists. */
export function vinesGrowBagActions(farmId: string, batchId: string, bag: VinesGrowBagFacts): ProductionAction[] {
  const actions: ProductionAction[] = [];
  const hasLiving = bag.living_plant_count > 0;
  if (hasLiving) actions.push({ kind: "record_loss", label: "Record plant loss" });
  actions.push(...placementNavigationActions(farmId, batchId, bag.batch_carrier_assignment_id, hasLiving));
  return actions;
}

/** A Vines (Batch, Gutter) aggregate row -- Batch-level Observation only.
 * UX-OPS-001C/R1: never Inspect Crop here. The aggregate spans several
 * placements, and an inspection must start from ONE exact placement (a
 * specific Grow Bag, via `vinesGrowBagActions`) -- never a Batch-only
 * inspection, and never silently narrowed to an arbitrary Grow Bag. */
export function vinesGroupActions(farmId: string, batchId: string, livingPlantCount: number): ProductionAction[] {
  if (livingPlantCount <= 0) return [];
  return [
    { kind: "record_observation", label: "Record observation", href: `/farms/${farmId}/observations?batchId=${batchId}` },
  ];
}

function placementNavigationActions(
  farmId: string,
  batchId: string,
  assignmentId: string,
  hasLiving: boolean,
): ProductionAction[] {
  const actions: ProductionAction[] = [];
  if (hasLiving) {
    actions.push({
      kind: "record_observation",
      label: "Record observation",
      href: `/farms/${farmId}/observations?batchId=${batchId}&assignmentId=${assignmentId}`,
    });
    // Exact placement preserved -- Inspect Crop never widens an
    // assignment-level entry to a Batch-wide pick.
    actions.push({
      kind: "inspect_crop",
      label: "Inspect Crop",
      href: `/farms/${farmId}/production/inspect?batchId=${batchId}&assignmentId=${assignmentId}`,
    });
  }
  // Reprint re-resolves current authoritative Batch/Carrier/Location on
  // the label route itself -- valid whenever the placement exists.
  actions.push({
    kind: "reprint_label",
    label: "Reprint label",
    href: `/farms/${farmId}/labels/batch_carrier_assignment/${assignmentId}`,
  });
  return actions;
}
