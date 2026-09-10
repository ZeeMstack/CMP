/** PLANNING-OPS-001: planning dates (`required_by_date`/`planned_sow_date`)
 * are plain calendar dates with no time-of-day or timezone component --
 * unlike `age.ts`'s farm-timezone-aware event timestamps, there is no
 * "farm-local" ambiguity to resolve here. Formats as "15 Oct 2026",
 * parsing the YYYY-MM-DD string at UTC noon so no browser timezone can
 * ever shift it to the adjacent calendar day. */
export function formatPlanDate(isoDate: string): string {
  const [year, month, day] = isoDate.split("-").map(Number);
  if (!year || !month || !day) return isoDate;
  const date = new Date(Date.UTC(year, month - 1, day, 12));
  return new Intl.DateTimeFormat("en-GB", { day: "2-digit", month: "short", year: "numeric", timeZone: "UTC" }).format(
    date,
  );
}
