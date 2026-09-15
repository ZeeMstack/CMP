const TOKEN_CHARSET_PATTERN = /^[A-Za-z0-9_-]+$/;

export type NormalizeScanInputResult = { token: string } | { error: string };

/** The one production origin every printed GrowCMP label's QR is built
 * against (`resolveTrustedOrigin()` server-side, see
 * `docs/domain/QR_SCAN_MODEL.md`). A pasted scan URL naming this origin is
 * always accepted here regardless of which host the browser itself is
 * currently running on -- an operator may be testing against a preview/dev
 * deployment while pasting a token copied from a genuine production label. */
export const GROWCMP_PRODUCTION_ORIGIN = "https://growcmp.com";

/** PILOT-SCAN-001E: the manual token/URL fallback's one normalization
 * step -- accepts either a raw QR token or a full GrowCMP scan URL
 * (`<a trusted origin>/q/<token>`) and extracts just the token. Never
 * resolves the entity itself (that authoritative resolution still happens
 * through the existing `/q/[token]` page); this is purely "what should I
 * navigate to next," never a second scan resolver.
 *
 * `allowedOrigins` is deliberately a required, explicit parameter rather
 * than a baked-in default: a URL claiming to be a GrowCMP scan link must
 * actually belong to one of these origins (the current application origin,
 * `GROWCMP_PRODUCTION_ORIGIN`, or -- in tests -- whatever fixture origin a
 * test wants to assert against). An absolute URL on any OTHER origin is
 * rejected even when its path shape is exactly `/q/<token>` -- otherwise
 * `https://evil.example/q/<token>` would extract and (per the security note
 * below) resolve as if it were a legitimate token, which is not "rejecting
 * arbitrary third-party URLs" even though it never navigates externally.
 *
 * Security note: this function returns a bare `token` string, never a
 * URL. The caller always constructs its own internal `/q/<token>`
 * destination from it (see `ScanEntryPage`) -- an arbitrary external URL
 * pasted here can therefore never be navigated to, regardless of what
 * origin/host it names, because that origin is discarded here and never
 * used for navigation. The origin allowlist above is an additional,
 * independent acceptance check -- it decides whether the input is treated
 * as a real GrowCMP scan link at all, not a navigation safeguard (the
 * navigation safeguard holds even without it). */
export function normalizeScanInput(rawInput: string, allowedOrigins: readonly string[]): NormalizeScanInputResult {
  const trimmed = rawInput.trim();
  if (!trimmed) {
    return { error: "Enter a QR token or scan link." };
  }

  let candidate = trimmed;
  try {
    const url = new URL(trimmed);
    // An absolute URL -- only ever trusted as a GrowCMP scan link if it
    // actually belongs to a trusted origin. Checked before the path shape
    // so a third-party origin is rejected outright, never on the strength
    // of merely having a `/q/<token>`-shaped path.
    if (!allowedOrigins.includes(url.origin)) {
      return { error: "That scan link doesn't belong to GrowCMP." };
    }
    const match = url.pathname.match(/^\/q\/([^/]+)\/?$/);
    if (!match) {
      return { error: "That doesn't look like a GrowCMP scan link." };
    }
    try {
      candidate = decodeURIComponent(match[1]);
    } catch {
      return { error: "That doesn't look like a valid QR token." };
    }
  } catch {
    // Not a full/absolute URL -- treat the whole trimmed input as a raw
    // token candidate instead.
  }

  if (!TOKEN_CHARSET_PATTERN.test(candidate)) {
    return { error: "That doesn't look like a valid QR token." };
  }
  return { token: candidate };
}
