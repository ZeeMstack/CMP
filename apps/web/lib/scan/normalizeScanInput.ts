const TOKEN_CHARSET_PATTERN = /^[A-Za-z0-9_-]+$/;

export type NormalizeScanInputResult = { token: string } | { error: string };

/** PILOT-SCAN-001E: the manual token/URL fallback's one normalization
 * step -- accepts either a raw QR token or a full GrowCMP scan URL
 * (`<any origin>/q/<token>`) and extracts just the token. Never resolves
 * the entity itself (that authoritative resolution still happens through
 * the existing `/q/[token]` page); this is purely "what should I navigate
 * to next," never a second scan resolver.
 *
 * Security note: this function returns a bare `token` string, never a
 * URL. The caller always constructs its own internal `/q/<token>`
 * destination from it (see `ScanEntryPage`) -- an arbitrary external URL
 * pasted here can therefore never be navigated to, regardless of what
 * origin/host it names, because that origin is discarded here and never
 * used for navigation. */
export function normalizeScanInput(rawInput: string): NormalizeScanInputResult {
  const trimmed = rawInput.trim();
  if (!trimmed) {
    return { error: "Enter a QR token or scan link." };
  }

  let candidate = trimmed;
  // A full URL, on whatever origin/host the operator's device happens to
  // be on (a Render preview URL, a LAN IP, localhost -- see
  // docs/domain/QR_SCAN_MODEL.md's own APP_BASE_URL warning): only the
  // `/q/<token>` path SHAPE is trusted, never the origin itself.
  try {
    const url = new URL(trimmed);
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
