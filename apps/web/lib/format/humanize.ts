/**
 * Turns an UPPER_SNAKE_CASE persisted enum code (quality-hold reason
 * codes, derivation kinds, etc.) into readable sentence-case copy, without
 * hardcoding any specific set of known codes -- new codes added to the
 * backend later must read sensibly here with no frontend change.
 */
export function humanizeEnumCode(value: string | null | undefined): string {
  if (!value) return "";
  const words = value
    .trim()
    .split(/[_\s]+/)
    .filter(Boolean)
    .map((word) => word.toLowerCase());
  if (words.length === 0) return "";
  const [first, ...rest] = words;
  return [first.charAt(0).toUpperCase() + first.slice(1), ...rest].join(" ");
}
