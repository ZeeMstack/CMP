import { ErrorState } from "@/components/ErrorState";
import { BoundedDataRegion } from "@/components/layout/BoundedDataRegion";
import { QueueList, QueueRow } from "@/components/layout/QueueRow";
import { LoadingSkeleton } from "@/components/LoadingSkeleton";
import type { HomeQueueSegment } from "@/lib/format/homeQueue";

/** UX-OPS-001B R1: renders one durable Home view's segments as ONE bounded
 * queue region (ticket §5.4/R1-4) -- every segment keeps its own inline
 * loading/error/empty state, so a failed source shows its own inline,
 * source-named unavailable row with retry without collapsing or hiding the
 * rest of the queue, but the segments together scroll inside a single
 * `BoundedDataRegion` rather than as independent unbounded page sections
 * (that independence was what let a long or failed source lengthen the
 * page itself). */
export function HomeQueueView({
  segments,
  selectedId,
  onSelect,
  onRetry,
}: {
  segments: HomeQueueSegment[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  onRetry: (segmentKey: string) => void;
}) {
  const anyRows = segments.some((s) => s.rows.length > 0);
  const allSettledEmpty = segments.every((s) => !s.isLoading && !s.error && s.rows.length === 0);

  if (allSettledEmpty && !anyRows) {
    return <p className="px-1 py-6 text-center text-sm text-wl-text-secondary">Nothing here right now.</p>;
  }

  return (
    <BoundedDataRegion label="Queue">
      <div className="flex flex-col gap-4 p-3">
        {segments.map((segment) => (
          <section key={segment.key} aria-label={segment.segmentLabel}>
            {segments.length > 1 && (
              <h3 className="mb-1.5 px-1 text-xs font-semibold uppercase tracking-wide text-wl-text-secondary">
                {segment.segmentLabel}
              </h3>
            )}
            {segment.isLoading && <LoadingSkeleton rows={2} label={`Loading ${segment.segmentLabel.toLowerCase()}`} />}
            {!segment.isLoading && Boolean(segment.error) && (
              <ErrorState error={segment.error} onRetry={() => onRetry(segment.key)} />
            )}
            {!segment.isLoading && !segment.error && segment.rows.length === 0 && (
              <p className="px-1 py-2 text-sm text-wl-text-secondary">{segment.emptyLabel}</p>
            )}
            {!segment.isLoading && !segment.error && segment.rows.length > 0 && (
              <div className="rounded-xl border border-wl-border bg-wl-surface-raised">
                <QueueList label={segment.segmentLabel}>
                  {segment.rows.map((row) => (
                    <QueueRow
                      key={row.id}
                      isSelected={row.id === selectedId}
                      onSelect={() => onSelect(row.id)}
                      sourceLabel={row.sourceLabel}
                      title={row.title}
                      context={row.context}
                      meta={row.meta}
                    />
                  ))}
                </QueueList>
              </div>
            )}
          </section>
        ))}
      </div>
    </BoundedDataRegion>
  );
}
