/**
 * Sowing-date and crop-age presentation. Age is a whole number of farm
 * calendar days between the sowing date and "now", both resolved in the
 * farm's own IANA timezone -- never the viewer's browser timezone, and
 * never a fractional 24-hour-period count (a batch sown at 23:50 farm-time
 * is "1 day old" ten minutes later, once the farm-local calendar date has
 * rolled over, not "0 days old"). `timeZone` is required (not optional)
 * here specifically to make it impossible to accidentally fall back to
 * browser-local time the way the general-purpose `formatDateTime` helpers
 * intentionally do.
 */

const DATE_KEY_FORMAT_CACHE = new Map<string, Intl.DateTimeFormat>();
const DATE_ONLY_FORMAT_CACHE = new Map<string, Intl.DateTimeFormat>();

function farmLocalDateKey(date: Date, timeZone: string): string {
  let formatter = DATE_KEY_FORMAT_CACHE.get(timeZone);
  if (!formatter) {
    // en-CA reliably formats as YYYY-MM-DD, which sorts/parses trivially.
    formatter = new Intl.DateTimeFormat("en-CA", {
      timeZone,
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
    });
    DATE_KEY_FORMAT_CACHE.set(timeZone, formatter);
  }
  return formatter.format(date);
}

/** Whole calendar days between two ISO instants, both resolved in
 * `timeZone`. Returns 0 for the same farm-local calendar date. */
export function calendarDaysBetween(startIso: string, timeZone: string, now: Date = new Date()): number {
  const startKey = farmLocalDateKey(new Date(startIso), timeZone);
  const nowKey = farmLocalDateKey(now, timeZone);
  const startUtcMidnight = Date.parse(`${startKey}T00:00:00Z`);
  const nowUtcMidnight = Date.parse(`${nowKey}T00:00:00Z`);
  return Math.round((nowUtcMidnight - startUtcMidnight) / 86_400_000);
}

/** "08 Jun 2026" style, in the farm's timezone. */
export function formatDateOnly(isoValue: string, timeZone: string): string {
  let formatter = DATE_ONLY_FORMAT_CACHE.get(timeZone);
  if (!formatter) {
    formatter = new Intl.DateTimeFormat("en-GB", { timeZone, day: "2-digit", month: "short", year: "numeric" });
    DATE_ONLY_FORMAT_CACHE.set(timeZone, formatter);
  }
  return formatter.format(new Date(isoValue));
}

export type SowingAgeDescription =
  | { kind: "known"; sownDateLabel: string; ageDays: number }
  | { kind: "multiple_origins" }
  | { kind: "unknown" };

/**
 * Decides what Sown/Age should show from the batch's structured facts:
 * - `sown_effective_time` non-null -> one unambiguous sown date + age.
 * - `sown_effective_time` null but the batch has recorded sowing origins
 *   -> those origins disagree on when the batch was sown; never guess one.
 * - no sowing origins at all -> honestly unknown, not "0 days".
 */
export function describeSowingAndAge(
  sowingOriginCount: number,
  sownEffectiveTime: string | null,
  timeZone: string,
  now: Date = new Date(),
): SowingAgeDescription {
  if (sownEffectiveTime) {
    return {
      kind: "known",
      sownDateLabel: formatDateOnly(sownEffectiveTime, timeZone),
      ageDays: calendarDaysBetween(sownEffectiveTime, timeZone, now),
    };
  }
  if (sowingOriginCount > 0) {
    return { kind: "multiple_origins" };
  }
  return { kind: "unknown" };
}
