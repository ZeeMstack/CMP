import Link from "next/link";

import { PlacementSummary } from "@/components/PlacementSummary";
import { StatusBadge } from "@/components/StatusBadge";
import {
  tableBodyDividerClass,
  tableHeadRowClass,
  tableRowHoverClass,
  tableTdClass,
  tableThClass,
  tableWrapperClass,
} from "@/components/ui/table";
import type { BatchOperationalContext } from "@/lib/api/client";
import { describeSowingAndAge } from "@/lib/format/age";

function SownAge({ batch, farmTimezone }: { batch: BatchOperationalContext; farmTimezone?: string }) {
  if (!farmTimezone) return <span className="text-wl-text-secondary">—</span>;
  const description = describeSowingAndAge(batch.sowing_origins.length, batch.sown_effective_time, farmTimezone);
  if (description.kind === "known") {
    return (
      <span>
        {description.sownDateLabel} · {description.ageDays}d
      </span>
    );
  }
  if (description.kind === "multiple_origins") {
    return <span className="text-wl-text-secondary">Multiple sowing origins</span>;
  }
  return <span className="text-wl-text-secondary">—</span>;
}

/** "Active" is the common case and deliberately renders as plain muted
 * text, not a badge -- so it never visually dominates every row. Closed
 * and superseded are the states an operator actually needs to notice, so
 * they keep the badge treatment. */
function StateCell({ state }: { state: string }) {
  if (state === "active") return <span className="text-xs text-wl-text-secondary">Active</span>;
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
      <div className={`hidden md:block ${tableWrapperClass}`}>
        <table className="w-full text-left text-sm">
          <thead>
            <tr className={tableHeadRowClass}>
              <th className={tableThClass}>Batch</th>
              <th className={tableThClass}>Crop / Variety</th>
              <th className={tableThClass}>Stage</th>
              <th className={tableThClass}>Placement</th>
              <th className={tableThClass}>Sown / Age</th>
              <th className={tableThClass}>Attention</th>
              <th className={tableThClass}>State</th>
            </tr>
          </thead>
          <tbody className={tableBodyDividerClass}>
            {batches.map((batch) => (
              <tr key={batch.id} className={tableRowHoverClass}>
                <td className={tableTdClass}>
                  <Link
                    href={`/farms/${farmId}/crop-batches/${batch.id}`}
                    className="font-medium text-wl-brand hover:underline"
                  >
                    {batch.code}
                  </Link>
                </td>
                <td className={tableTdClass}>
                  {batch.crop.common_name}
                  {batch.variety ? ` — ${batch.variety.name}` : ""}
                </td>
                <td className={tableTdClass}>{batch.current_stage.name}</td>
                <td className={`${tableTdClass} text-wl-text-secondary`}>
                  <PlacementSummary placement={batch.placement} />
                </td>
                <td className={`${tableTdClass} text-wl-text-secondary`}>
                  <SownAge batch={batch} farmTimezone={farmTimezone} />
                </td>
                <td className={tableTdClass}>
                  <AttentionCell batch={batch} />
                </td>
                <td className={tableTdClass}>
                  <StateCell state={batch.state} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Mobile: cards -- batch code, crop, stage, placement, hold badge,
          and sown/age (where space permits) must all stay visible; none of
          this is desktop-only. */}
      <ul className="space-y-2 md:hidden">
        {batches.map((batch) => (
          <li key={batch.id}>
            <Link
              href={`/farms/${farmId}/crop-batches/${batch.id}`}
              className="block rounded-lg border border-wl-border bg-wl-surface-raised p-3 hover:border-wl-brand"
            >
              <div className="flex items-center justify-between gap-2">
                <span className="font-medium text-wl-text">{batch.code}</span>
                <div className="flex items-center gap-1.5">
                  <AttentionCell batch={batch} />
                  <StateCell state={batch.state} />
                </div>
              </div>
              <p className="mt-1 text-sm text-wl-text-secondary">
                {batch.crop.common_name}
                {batch.variety ? ` — ${batch.variety.name}` : ""} · {batch.current_stage.name}
              </p>
              <p className="mt-1 text-xs text-wl-text-secondary">
                <PlacementSummary placement={batch.placement} />
              </p>
              <p className="mt-1 text-xs text-wl-text-secondary">
                <SownAge batch={batch} farmTimezone={farmTimezone} />
              </p>
            </Link>
          </li>
        ))}
      </ul>
    </>
  );
}
