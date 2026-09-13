/** PILOT-BLOCKER-008 A8: shared local-clock helpers for `datetime-local`/
 * split date+time input defaults. Every one of these MUST use local `Date`
 * getters (`getFullYear`, `getHours`, ...) -- never `toISOString()`/UTC
 * getters -- because a browser `type="date"`/`type="time"`/`type="datetime-
 * local"` input displays and re-parses its value as the operator's LOCAL
 * wall-clock time. Building a default from UTC components and displaying it
 * as if it were local silently shifts the recorded instant by the local
 * UTC offset (worst near a timezone's midnight, where the calendar day
 * itself can be wrong). This was previously copy-pasted verbatim into three
 * call sites (`nowLocalDateTime` in the Inventory, Quality, and Putaway
 * pages) -- centralized here as the one place this logic lives. */

function pad(n: number): string {
  return String(n).padStart(2, "0");
}

/** `YYYY-MM-DD` for a `type="date"` input's local "today". */
export function nowLocalDate(): string {
  const now = new Date();
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

/** `HH:mm` for a `type="time"` input's local "now". */
export function nowLocalTime(): string {
  const now = new Date();
  return `${pad(now.getHours())}:${pad(now.getMinutes())}`;
}

/** `YYYY-MM-DDTHH:mm` for a `type="datetime-local"` input's local "now". */
export function nowLocalDateTime(): string {
  return `${nowLocalDate()}T${nowLocalTime()}`;
}
