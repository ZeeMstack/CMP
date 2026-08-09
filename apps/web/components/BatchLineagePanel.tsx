import Link from "next/link";

import { EmptyState } from "@/components/EmptyState";
import type { BatchLineageRead } from "@/lib/api/client";
import { formatDateTime } from "@/lib/format/datetime";

function LineageList({
  title,
  events,
  farmId,
  farmTimezone,
}: {
  title: string;
  events: BatchLineageRead["parents"];
  farmId: string;
  farmTimezone?: string;
}) {
  return (
    <div>
      <h3 className="mb-2 text-sm font-semibold text-ink">{title}</h3>
      {events.length === 0 ? (
        <p className="text-sm text-ink-muted">None.</p>
      ) : (
        <ul className="space-y-2">
          {events.map((event) => (
            <li
              key={`${event.derivation_event_id}-${event.batch.id}`}
              className="rounded-md border border-border-subtle p-3 text-sm"
            >
              <Link
                href={`/farms/${farmId}/crop-batches/${event.batch.id}`}
                className="font-medium text-brand-700 hover:underline"
              >
                {event.batch.code}
              </Link>
              <p className="mt-0.5 text-ink-muted">
                {event.derivation_kind} · {formatDateTime(event.effective_time, farmTimezone)}
              </p>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** Simple parent/child lineage list -- not the full CMP-019 traceability
 * visualization, which is out of scope for FE-001. */
export function BatchLineagePanel({ lineage, farmId, farmTimezone }: { lineage: BatchLineageRead; farmId: string; farmTimezone?: string }) {
  if (lineage.parents.length === 0 && lineage.children.length === 0) {
    return <EmptyState title="No lineage recorded" description="This batch has no recorded split/merge relationships." />;
  }
  return (
    <div className="grid gap-6 sm:grid-cols-2">
      <LineageList title="Parents" events={lineage.parents} farmId={farmId} farmTimezone={farmTimezone} />
      <LineageList title="Children" events={lineage.children} farmId={farmId} farmTimezone={farmTimezone} />
    </div>
  );
}
