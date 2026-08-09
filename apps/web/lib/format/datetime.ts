/**
 * Centralized date/time presentation. Backend `effective_time`/
 * `recorded_time`/etc. fields are ISO-8601 with an explicit UTC offset.
 * When a farm's own IANA timezone (`FarmRead.timezone`) is known, times are
 * shown in that timezone -- this is what "operational time" means to
 * someone standing in the farm. Do not call `Date.toLocaleString()`
 * directly in components; use these helpers so the farm-timezone rule is
 * applied consistently everywhere.
 */

const DATE_TIME_FORMAT_CACHE = new Map<string, Intl.DateTimeFormat>();

function getFormatter(timeZone: string | undefined): Intl.DateTimeFormat {
  const key = timeZone ?? "__browser__";
  let formatter = DATE_TIME_FORMAT_CACHE.get(key);
  if (!formatter) {
    formatter = new Intl.DateTimeFormat(undefined, {
      dateStyle: "medium",
      timeStyle: "short",
      timeZone,
    });
    DATE_TIME_FORMAT_CACHE.set(key, formatter);
  }
  return formatter;
}

/**
 * Formats an ISO datetime string. Pass the owning farm's `timezone` field
 * when available so the result reflects farm-local operational time; when
 * omitted, falls back to the viewer's browser timezone (labelled as such by
 * callers where the distinction matters).
 */
export function formatDateTime(isoValue: string | null | undefined, timeZone?: string): string {
  if (!isoValue) return "—";
  const date = new Date(isoValue);
  if (Number.isNaN(date.getTime())) return "—";
  return getFormatter(timeZone).format(date);
}

export function formatDateTimeWithZoneLabel(isoValue: string | null | undefined, timeZone?: string): string {
  const formatted = formatDateTime(isoValue, timeZone);
  if (formatted === "—") return formatted;
  return timeZone ? `${formatted} (${timeZone})` : `${formatted} (your local time)`;
}
