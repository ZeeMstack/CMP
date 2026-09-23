/** UX-OPS-001B R1 (blocker #6): a compact "how long has this been in its
 * current state" string -- meaningful elapsed-state context for a queue
 * row, never just a raw date (a floor operator scanning a queue needs "how
 * stale is this", not a calendar lookup). Pure/testable, mirrors this
 * codebase's other `lib/format/*` pure-formatter convention. */
export function formatElapsedSince(iso: string, now: Date = new Date()): string {
  const then = new Date(iso).getTime();
  const diffMs = Math.max(0, now.getTime() - then);
  const minutes = Math.floor(diffMs / 60_000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m in state`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h in state`;
  const days = Math.floor(hours / 24);
  return `${days}d in state`;
}
