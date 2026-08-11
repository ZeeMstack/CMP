/**
 * The ONLY function anywhere in the frontend that turns an untrusted
 * string into a same-app navigation target (AUTH-001B3). Used both to
 * build the `returnTo` CMP puts on a `/login` redirect (from its own,
 * already-trusted current path -- a formality) and, security-critically,
 * to validate the `?returnTo=` query value a user could arrive at
 * `/login` with (fully untrusted).
 *
 * Only ever returns a safe, local, relative application path -- never an
 * absolute URL, protocol-relative URL, or any of Auth0/CMP's own
 * auth-entry routes (which would create a redirect loop or let this
 * parameter be used to reach a route this gate is specifically meant to
 * protect).
 */

export const RETURN_TO_FALLBACK = "/farms";

const BLOCKED_EXACT = new Set(["/login"]);
const BLOCKED_PREFIXES = ["/auth", "/api"];

export function sanitizeReturnTo(candidate: string | null | undefined): string {
  if (!candidate) return RETURN_TO_FALLBACK;

  let decoded: string;
  try {
    decoded = decodeURIComponent(candidate);
  } catch {
    return RETURN_TO_FALLBACK;
  }

  // Must be exactly one leading "/" -- rejects absolute URLs
  // (https://evil.example), scheme URLs (javascript:, data:, mailto:),
  // and protocol-relative URLs (//evil.example, which browsers resolve
  // against the *current* protocol but a different host).
  if (!decoded.startsWith("/") || decoded.startsWith("//")) {
    return RETURN_TO_FALLBACK;
  }

  // Backslashes are how "/\evil.example"-style tricks become a
  // protocol-relative URL after browser/UA normalization -- reject
  // outright rather than trying to allow-list every normalization quirk.
  if (decoded.includes("\\")) {
    return RETURN_TO_FALLBACK;
  }

  const [pathOnly] = decoded.split(/[?#]/);

  // Never a target inside another redirect/auth-entry surface -- avoids
  // loops (returnTo pointing back at /login) and avoids this parameter
  // being usable to reach SDK-owned or server-only routes.
  if (BLOCKED_EXACT.has(pathOnly) || BLOCKED_PREFIXES.some((prefix) => pathOnly.startsWith(prefix))) {
    return RETURN_TO_FALLBACK;
  }

  return decoded;
}
