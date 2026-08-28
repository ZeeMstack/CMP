"use client";

const BALANCE_EPSILON = 0.001;

/** POSTHARVEST-OPS-001G: shared live-reconciliation display for Grading
 * ("input presented = rejected + loss + sample + remainder + graded
 * outputs") and Packing ("consumed input = packed output + process loss +
 * rejected"). One component so Configure/Review/History never hand-roll
 * their own copy of this arithmetic or its balanced/unbalanced styling. */
export function ReconciliationSummary({
  inputLabel,
  inputValue,
  parts,
  unit,
}: {
  inputLabel: string;
  inputValue: number;
  parts: { label: string; value: number }[];
  unit: string;
}) {
  const accounted = parts.reduce((sum, p) => sum + (Number.isFinite(p.value) ? p.value : 0), 0);
  const diff = inputValue - accounted;
  const balanced = Math.abs(diff) <= BALANCE_EPSILON;

  return (
    <div
      className={`rounded-xl border p-3 text-sm ${
        balanced ? "border-border-subtle bg-surface-subtle" : "border-red-300 bg-red-50"
      }`}
    >
      <div className="flex items-center justify-between">
        <span className="font-medium text-ink">{inputLabel}</span>
        <span className="font-semibold text-ink">
          {inputValue.toLocaleString(undefined, { maximumFractionDigits: 3 })} {unit}
        </span>
      </div>
      <dl className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 sm:grid-cols-3">
        {parts.map((part) => (
          <div key={part.label}>
            <dt className="text-xs text-ink-muted">{part.label}</dt>
            <dd className="text-ink">
              {(Number.isFinite(part.value) ? part.value : 0).toLocaleString(undefined, { maximumFractionDigits: 3 })}{" "}
              {unit}
            </dd>
          </div>
        ))}
      </dl>
      <div
        className={`mt-2 flex items-center justify-between border-t pt-2 text-xs font-medium ${
          balanced ? "border-border-subtle text-ink-muted" : "border-red-200 text-red-800"
        }`}
      >
        <span>{balanced ? "Balanced" : "Out of balance"}</span>
        <span>
          Accounted {accounted.toLocaleString(undefined, { maximumFractionDigits: 3 })} {unit}
          {!balanced && ` (${diff > 0 ? "short" : "over"} by ${Math.abs(diff).toLocaleString(undefined, { maximumFractionDigits: 3 })} ${unit})`}
        </span>
      </div>
    </div>
  );
}
