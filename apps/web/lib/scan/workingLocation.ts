/** PILOT-SCAN-001F: "I am currently working here" -- a purely local,
 * operator-declared browser context, never a farm record. It is never
 * written by the backend, never read by any domain command, and expires
 * on its own; nothing about its presence changes what a destination page
 * is authorized to do (CLAUDE.md rule 11 stays with the backend). See
 * `docs/domain/QR_SCAN_MODEL.md`'s "Location-first scan validation"
 * section for the full contract this exists to support.
 *
 * Stored in `localStorage` (not `sessionStorage`): the working session must
 * survive the device's native camera app opening the NEXT `/q/<token>` scan
 * in a fresh tab, which a per-tab `sessionStorage` value would not reach. */
export interface WorkingLocation {
  /** The scanned Location's own authoritative id -- never derived from a
   * display string (CLAUDE.md rule 3: locations are UUID-based). */
  locationId: string;
  farmId: string;
  /** Display-only fields, never compared for validation. */
  code: string;
  pathString: string;
  selectedAt: string;
  expiresAt: string;
}

const STORAGE_KEY = "growcmp.workingLocation.v1";
const TTL_MS = 12 * 60 * 60 * 1000;

export const WORKING_LOCATION_STORAGE_KEY = STORAGE_KEY;
export const WORKING_LOCATION_TTL_MS = TTL_MS;

function isWorkingLocation(value: unknown): value is WorkingLocation {
  if (!value || typeof value !== "object") return false;
  const v = value as Record<string, unknown>;
  return (
    typeof v.locationId === "string" &&
    typeof v.farmId === "string" &&
    typeof v.code === "string" &&
    typeof v.pathString === "string" &&
    typeof v.selectedAt === "string" &&
    typeof v.expiresAt === "string"
  );
}

/** Reads the working location, transparently discarding (and cleaning up)
 * an expired one -- callers never need to separately check `expiresAt`.
 * `now` is only ever overridden by tests. */
export function readWorkingLocation(now: Date = new Date()): WorkingLocation | null {
  if (typeof window === "undefined") return null;
  let raw: string | null;
  try {
    raw = window.localStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
  if (!raw) return null;

  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    clearWorkingLocationStorage();
    return null;
  }
  if (!isWorkingLocation(parsed) || Number.isNaN(new Date(parsed.expiresAt).getTime())) {
    clearWorkingLocationStorage();
    return null;
  }
  if (new Date(parsed.expiresAt).getTime() <= now.getTime()) {
    clearWorkingLocationStorage();
    return null;
  }
  return parsed;
}

/** Establishes (or deliberately replaces) the working location -- always a
 * full 12-hour window from `now`, never extended/topped-up by anything
 * other than this explicit call. */
export function writeWorkingLocation(
  input: { locationId: string; farmId: string; code: string; pathString: string },
  now: Date = new Date(),
): WorkingLocation {
  const value: WorkingLocation = {
    ...input,
    selectedAt: now.toISOString(),
    expiresAt: new Date(now.getTime() + TTL_MS).toISOString(),
  };
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(value));
  } catch {
    // Best-effort persistence only (private window, blocked site data) --
    // the caller's own in-memory state still reflects the selection for
    // this render; it just will not survive navigation in that browser.
  }
  return value;
}

export function clearWorkingLocationStorage(): void {
  try {
    window.localStorage.removeItem(STORAGE_KEY);
  } catch {
    // best-effort only
  }
}
