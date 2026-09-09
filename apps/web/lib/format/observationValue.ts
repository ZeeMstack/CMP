import type { ObservationValueRead } from "@/lib/api/client";

/** The backend serializes `Decimal` as a fixed-scale string (e.g.
 * `"18.500"` for a column with scale 3) -- truthful for storage, but
 * trailing zeros read as noise to an operator glancing at a log. Strips
 * them via a numeric round-trip; falls back to the raw string on the rare
 * value `Number()` can't parse rather than hiding it. */
function normalizeDecimalString(raw: string): string {
  const n = Number(raw);
  return Number.isFinite(n) ? String(n) : raw;
}

/** AGRONOMY-OPS-001: operator-friendly rendering of one recorded
 * Observation value -- never the raw typed-column shape (`{"value_decimal":
 * "18.500"}`), never a raw boolean literal, always the definition's own
 * configured unit when present. Mirrors this codebase's established rule
 * (CLAUDE.md "Value Presentation"): use only backend-supplied unit/display
 * metadata, never a fabricated one. */
export function formatObservationValue(value: ObservationValueRead): string {
  const unit = value.definition.unit ? ` ${value.definition.unit}` : "";
  switch (value.definition.value_type) {
    case "integer":
      return value.value_integer === null ? "—" : `${value.value_integer.toLocaleString()}${unit}`;
    case "decimal":
      return value.value_decimal === null ? "—" : `${normalizeDecimalString(value.value_decimal)}${unit}`;
    case "percentage":
      return value.value_decimal === null ? "—" : `${normalizeDecimalString(value.value_decimal)}%`;
    case "boolean":
      return value.value_boolean === null ? "—" : value.value_boolean ? "Yes" : "No";
    case "text":
      return value.value_text ?? "—";
    default:
      return "—";
  }
}

/** Compact target label for one recorded value: the specific carrier it was
 * measured on, or "Whole batch" when the definition is batch-scoped
 * (`carrier` is null). Never a raw `batch_carrier_assignment_id`. */
export function formatObservationValueTarget(value: ObservationValueRead): string {
  return value.carrier ? value.carrier.code : "Whole batch";
}
