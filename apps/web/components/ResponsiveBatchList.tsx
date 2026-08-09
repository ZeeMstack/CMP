import Link from "next/link";

import { StatusBadge } from "@/components/StatusBadge";
import type { CropBatchRead } from "@/lib/api/client";
import { formatDateTime } from "@/lib/format/datetime";

const STATE_TONE: Record<string, "active" | "closed" | "neutral"> = {
  active: "active",
  closed: "closed",
  superseded: "closed",
};

export function ResponsiveBatchList({
  batches,
  farmId,
  farmTimezone,
}: {
  batches: CropBatchRead[];
  farmId: string;
  farmTimezone?: string;
}) {
  return (
    <>
      {/* Desktop: table */}
      <table className="hidden w-full text-left text-sm md:table">
        <thead>
          <tr className="border-b border-border-subtle text-xs uppercase tracking-wide text-ink-muted">
            <th className="py-2 pr-4 font-medium">Code</th>
            <th className="py-2 pr-4 font-medium">Crop</th>
            <th className="py-2 pr-4 font-medium">Stage</th>
            <th className="py-2 pr-4 font-medium">State</th>
            <th className="py-2 pr-4 font-medium">Created</th>
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
              <td className="py-2 pr-4">
                <StatusBadge label={batch.state} tone={STATE_TONE[batch.state] ?? "neutral"} />
              </td>
              <td className="py-2 pr-4 text-ink-muted">
                {formatDateTime(batch.created_effective_time, farmTimezone)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {/* Mobile: cards */}
      <ul className="space-y-2 md:hidden">
        {batches.map((batch) => (
          <li key={batch.id}>
            <Link
              href={`/farms/${farmId}/crop-batches/${batch.id}`}
              className="block rounded-lg border border-border-subtle bg-surface p-3 hover:border-brand-300"
            >
              <div className="flex items-center justify-between gap-2">
                <span className="font-medium text-ink">{batch.code}</span>
                <StatusBadge label={batch.state} tone={STATE_TONE[batch.state] ?? "neutral"} />
              </div>
              <p className="mt-1 text-sm text-ink-muted">
                {batch.crop.common_name}
                {batch.variety ? ` — ${batch.variety.name}` : ""} · {batch.current_stage.name}
              </p>
              <p className="mt-1 text-xs text-ink-muted">
                Created {formatDateTime(batch.created_effective_time, farmTimezone)}
              </p>
            </Link>
          </li>
        ))}
      </ul>
    </>
  );
}
