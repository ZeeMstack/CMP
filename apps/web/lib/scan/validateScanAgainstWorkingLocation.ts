import type { ScanContext } from "@/lib/api/client";
import type { WorkingLocation } from "@/lib/scan/workingLocation";

/** PILOT-SCAN-001F: SCAN CONTEXT != FARM TRANSACTION. This is a pure,
 * side-effect-free comparison of two already-authoritative facts (the
 * operator's declared working location and the scanned resource's own
 * current authoritative location) -- it never fetches anything, never
 * mutates anything, and its result is never itself proof of a farm
 * transaction. See `docs/domain/QR_SCAN_MODEL.md`. */
export type LocationValidationResult =
  | { kind: "NO_WORKING_LOCATION" }
  | { kind: "MATCH_EXACT"; pathString: string }
  | { kind: "MATCH_DESCENDANT"; pathString: string }
  | { kind: "MISMATCH"; reason: "different_farm" | "different_location"; pathString: string | null }
  | { kind: "CANNOT_VALIDATE"; reason: string }
  | { kind: "HISTORICAL"; pathString: string | null };

type LocationFact =
  | { kind: "historical"; pathString: string | null }
  | { kind: "resolved"; farmId: string; ids: readonly string[]; pathString: string }
  | { kind: "unresolved"; reason: string };

/** One authoritative physical-location fact per entity type, read straight
 * off the already-resolved `ScanContext` -- never a second fetch, never a
 * new resolver. A Batch-level scan deliberately NEVER produces a
 * "resolved" fact (a Batch may occupy several Carriers/Locations at once;
 * only its own Placement/Carrier QR identifies one specific physical
 * portion), and Harvest/Graded/Finished-Goods lots have no authoritative
 * physical location modeled at all yet -- both are honest CANNOT_VALIDATE,
 * never a guessed match. */
function extractLocationFact(ctx: ScanContext): LocationFact {
  switch (ctx.entity_type) {
    case "location":
      return { kind: "resolved", farmId: ctx.farm_id, ids: ctx.location.ids, pathString: ctx.location.path_string };
    case "carrier":
      return ctx.current_location
        ? { kind: "resolved", farmId: ctx.farm_id, ids: ctx.current_location.ids, pathString: ctx.current_location.path_string }
        : { kind: "unresolved", reason: ctx.unresolved_reason ?? "This Carrier has no current location." };
    case "asset":
      return ctx.current_location
        ? { kind: "resolved", farmId: ctx.farm_id, ids: ctx.current_location.ids, pathString: ctx.current_location.path_string }
        : { kind: "unresolved", reason: ctx.unresolved_reason ?? "This Asset has no current location." };
    case "batch_carrier_assignment":
      // A released placement is historically traceable, never a current
      // MATCH -- checked before location resolution so a stale record
      // that happens to still carry a location can never be compared.
      if (ctx.released) {
        return { kind: "historical", pathString: ctx.current_location?.path_string ?? null };
      }
      return ctx.current_location
        ? { kind: "resolved", farmId: ctx.farm_id, ids: ctx.current_location.ids, pathString: ctx.current_location.path_string }
        : { kind: "unresolved", reason: ctx.unresolved_reason ?? "This placement has no current location." };
    case "crop_batch":
      if (ctx.placements.length === 0) {
        return { kind: "unresolved", reason: "This Batch has no active placement." };
      }
      if (ctx.placements.length > 1) {
        return {
          kind: "unresolved",
          reason:
            "This Batch has multiple active placements. Scan the physical Placement or Carrier label to validate its exact location.",
        };
      }
      // Exactly one active placement: still deliberately not treated as
      // proof of exact physical placement (PILOT-SCAN-001F) -- a
      // Batch-level QR is never sufficient on its own; scanning the
      // Placement/Carrier itself is what proves the exact location.
      return {
        kind: "unresolved",
        reason:
          "A Batch-level scan cannot prove exactly where its active placement currently is. Scan the Placement or Carrier label to validate its exact location.",
      };
    case "harvested_produce_lot":
    case "graded_produce_lot":
    case "finished_goods_lot":
      return { kind: "unresolved", reason: "This context does not expose an authoritative physical location." };
  }
}

export function validateScanAgainstWorkingLocation(
  workingLocation: WorkingLocation | null,
  ctx: ScanContext,
): LocationValidationResult {
  if (!workingLocation) return { kind: "NO_WORKING_LOCATION" };

  const fact = extractLocationFact(ctx);
  if (fact.kind === "historical") return { kind: "HISTORICAL", pathString: fact.pathString };
  if (fact.kind === "unresolved") return { kind: "CANNOT_VALIDATE", reason: fact.reason };

  if (fact.farmId !== workingLocation.farmId) {
    return { kind: "MISMATCH", reason: "different_farm", pathString: fact.pathString };
  }

  const leafId = fact.ids[fact.ids.length - 1];
  if (leafId === workingLocation.locationId) {
    return { kind: "MATCH_EXACT", pathString: fact.pathString };
  }

  const ancestorIds = fact.ids.slice(0, -1);
  if (ancestorIds.includes(workingLocation.locationId)) {
    return { kind: "MATCH_DESCENDANT", pathString: fact.pathString };
  }

  // Every other case -- an unrelated branch, or the "reverse" case where
  // the resource's own recorded location is an ANCESTOR of (coarser than)
  // the working location -- is a MISMATCH, never an automatic match: a
  // coarser recorded location is never proof the resource is physically
  // at the narrower working location it happens to contain.
  return { kind: "MISMATCH", reason: "different_location", pathString: fact.pathString };
}

/** The only result that withholds action links is MISMATCH -- CANNOT_VALIDATE
 * leaves every action exactly as the backend sent it (its own destination
 * page still performs its own independent domain validation; this is an
 * operator-context safety layer, never a substitute for or change to
 * backend authorization), and MATCH/HISTORICAL/NO_WORKING_LOCATION never
 * filtered anything to begin with (a released placement's own backend
 * response already omits its Harvest action -- see
 * `qr_service.resolve_scan_context`'s `batch_carrier_assignment` branch).
 * The label set below is exactly `qr_service.py`'s own current physical-
 * operation action labels (`ScanAction.label` strings) -- a purely
 * client-side, defense-in-depth list; it changes no backend authorization
 * and a drift here would only ever fail open (an operation link staying
 * visible), never fail closed on something safe. */
const WITHHELD_UNDER_MISMATCH: ReadonlySet<string> = new Set([
  "Record Observation",
  "Harvest",
  "Grade this lot",
  "Pack",
  "Dispatch",
  "Cold Storage",
]);

export function filterActionsForLocationValidation<T extends { label: string }>(
  actions: readonly T[],
  result: LocationValidationResult,
): T[] {
  if (result.kind !== "MISMATCH") return [...actions];
  return actions.filter((action) => !WITHHELD_UNDER_MISMATCH.has(action.label));
}
