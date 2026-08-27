/**
 * POSTHARVEST-OPS-001G PRE-COMMIT CORRECTION: a GradeDefinitionVersion or
 * PackSpecificationVersion is selectable for a transaction based on its
 * historical window at the transaction's own `effective_time` -- never on
 * its current lifecycle status alone ("is it active right now").
 *
 * DRAFT is never selectable (it has never been activated, so it has no
 * effective window at all). ACTIVE or RETIRED are selectable exactly when:
 *
 *   effective_from <= effective_time
 *   AND (effective_until IS NULL OR effective_time < effective_until)
 *
 * This means a historically-valid RETIRED version remains selectable for a
 * backdated transaction inside its own historical window, and a currently
 * ACTIVE version is NOT selectable for a transaction backdated to before it
 * was activated. Both list APIs already return `status`, `effective_from`,
 * and `effective_until` for every version regardless of status (status
 * omitted from the request), so this is pure client-side filtering over
 * data the backend already exposes -- no backend change needed.
 */

export interface VersionLifecycle {
  status: string;
  effective_from: string | null;
  effective_until: string | null;
}

export function isVersionSelectableAt(version: VersionLifecycle, effectiveTimeIso: string): boolean {
  if (version.status === "draft") return false;
  if (!effectiveTimeIso || version.effective_from == null) return false;

  const effectiveTime = new Date(effectiveTimeIso).getTime();
  const from = new Date(version.effective_from).getTime();
  if (Number.isNaN(effectiveTime) || Number.isNaN(from)) return false;
  if (effectiveTime < from) return false;

  if (version.effective_until != null) {
    const until = new Date(version.effective_until).getTime();
    if (!Number.isNaN(until) && effectiveTime >= until) return false;
  }
  return true;
}

export function selectableVersionsAt<T extends VersionLifecycle>(versions: T[], effectiveTimeIso: string): T[] {
  return versions.filter((v) => isVersionSelectableAt(v, effectiveTimeIso));
}
