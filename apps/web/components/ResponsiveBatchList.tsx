import Link from "next/link";

import { PlacementSummary } from "@/components/PlacementSummary";
import { StatusBadge } from "@/components/StatusBadge";
import type { BatchOperationalContext } from "@/lib/api/client";
import { describeSowingAndAge } from "@/lib/format/age";

function SownAge({ batch, farmTimezone }: { batch: BatchOperationalContext; farmTimezone?: string }) {
  if (!farmTimezone) return <span className="text-ink-muted">—</span>;
  const description = describeSowingAndAge(batch.sowing_origins.length, batch.sown_effective_time, farmTimezone);
  if (description.kind === "known") {
    return (
      <span>
        {description.sownDateLabel} · {description.ageDays}d
      </span>
    );
  }
  if (description.kind === "multiple_origins") {
    return <span className="text-ink-muted">Multiple sowing origins</span>;
  }
  return <span className="text-ink-muted">—</span>;
}

/** "Active" is the common case and deliberately renders as plain muted
 * text, not a badge -- so it never visually dominates every row. Closed
 * and superseded are the states an operator actually needs to notice, so
 * they keep the badge treatment. */
function StateCell({ state }: { state: string }) {
  if (state === "active") return <span className="text-xs text-ink-muted">Active</span>;
  return <StatusBadge label={state} tone="closed" />;
}

function AttentionCell({ batch }: { batch: BatchOperationalContext }) {
  if (batch.open_quality_hold_count <= 0) return null;
  return <StatusBadge label="On hold" tone="attention" />;
}

export function ResponsiveBatchList({
  batches,
  farmId,
  farmTimezone,
}: {
  batches: BatchOperationalContext[];
  farmId: string;
  farmTimezone?: string;
}) {
  return (
    <>
      {/* Desktop: table */}
      <table className="hidden w-full text-left text-sm md:table">
        <thead>
          <tr className="border-b border-border-subtle text-xs uppercase tracking-wide text-ink-muted">
            <th className="py-2 pr-4 font-medium">Batch</th>
            <th className="py-2 pr-4 font-medium">Crop / Variety</th>
            <th className="py-2 pr-4 font-medium">Stage</th>
            <th className="py-2 pr-4 font-medium">Placement</th>
            <th className="py-2 pr-4 font-medium">Sown / Age</th>
            <th className="py-2 pr-4 font-medium">Attention</th>
            <th className="py-2 pr-4 font-medium">State</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border-subtle">
          {batches.map((batch) => (
            <tr key={batch.id} className="hover:bg-surface-subtle">
              <td className="py-2 pr-4">
                <Link
                  href={`/farms/${farmId}/crop-batches/${batch.id}`}
                  className="font-medium text-brand-700 hover:underline"
                >
                  {batch.code}
                </Link>
              </td>
              <td className="py-2 pr-4">
                {batch.crop.common_name}
                {batch.variety ? ` — ${batch.variety.name}` : ""}
              </td>
              <td className="py-2 pr-4">{batch.current_stage.name}</td>
              <td className="py-2 pr-4 text-ink-muted">
                <PlacementSummary placement={batch.placement} />
              </td>
              <td className="py-2 pr-4 text-ink-muted">
                <SownAge batch={batch} farmTimezone={farmTimezone} />
              </td>
              <td className="py-2 pr-4">
                <AttentionCell batch={batch} />
              </td>
              <td className="py-2 pr-4">
                <StateCell state={batch.state} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {/* Mobile: cards -- batch code, crop, stage, placement, hold badge,
          and sown/age (where space permits) must all stay visible; none of
          this is desktop-only. */}
      <ul className="space-y-2 md:hidden">
        {batches.map((batch) => (
          <li key={batch.id}>
            <Link
              href={`/farms/${farmId}/crop-batches/${batch.id}`}
              className="block rounded-lg border border-border-subtle bg-surface p-3 hover:border-brand-300"
            >
              <div className="flex items-center justify-between gap-2">
                <span className="font-medium text-ink">{batch.code}</span>
                <div className="flex items-center gap-1.5">
                  <AttentionCell batch={batch} />
                  <StateCell state={batch.state} />
                </div>
              </div>
              <p className="mt-1 text-sm text-ink-muted">
                {batch.crop.common_name}
                {batch.variety ? ` — ${batch.variety.name}` : ""} · {batch.current_stage.name}
              </p>
              <p className="mt-1 text-xs text-ink-muted">
                <PlacementSummary placement={batch.placement} />
              </p>
              <p className="mt-1 text-xs text-ink-muted">
                <SownAge batch={batch} farmTimezone={farmTimezone} />
              </p>
            </Link>
          </li>
        ))}
      </ul>
    </>
  );
}
