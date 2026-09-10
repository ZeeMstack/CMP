/** PLANNING-OPS-001: renders a decimal-string quantity + UOM code as
 * "30,000 kg" -- thousands-grouped, trailing zeros trimmed (the backend's
 * Numeric(18,3) scale is a storage detail, never shown to the planner). */
export function formatQuantity(value: string, uomCode: string): string {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return `${value} ${uomCode}`;
  const formatted = new Intl.NumberFormat("en-US", { maximumFractionDigits: 3 }).format(numeric);
  return `${formatted} ${uomCode}`;
}
