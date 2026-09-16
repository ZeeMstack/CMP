/** PILOT-AGRO-001B Part 3: client-side mirror of the backend's own
 * `GrowerInspectionCreate.validate_affected_within_inspected` check -- a
 * finding's `affected_count` may never exceed the inspection's own
 * `inspected_count`. Pure and independently testable so the "affected >
 * inspected blocked" proof does not require mounting the whole Inspect
 * Crop workspace. The backend re-validates this regardless (never trust
 * client-side validation alone) -- this only gives the operator immediate
 * feedback before a round trip. */
export function validateAffectedWithinInspected(
  inspectedCount: number | null,
  affectedCount: number | null,
): string | null {
  if (inspectedCount !== null && affectedCount !== null && affectedCount > inspectedCount) {
    return "Affected count cannot exceed inspected count.";
  }
  return null;
}
