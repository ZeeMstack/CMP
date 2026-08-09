import Link from "next/link";

import { EmptyState } from "@/components/EmptyState";
import type { BatchLineageRead } from "@/lib/api/client";
import { humanizeEnumCode } from "@/lib/format/humanize";

type LineageEvent = BatchLineageRead["parents"][number];

function lowerFirst(value: string): string {
  return value.length === 0 ? value : value.charAt(0).toLowerCase() + value.slice(1);
}

function groupByDerivationEvent(events: LineageEvent[]) {
  const groups = new Map<string, { kind: string; batches: LineageEvent["batch"][] }>();
  for (const event of events) {
    const existing = groups.get(event.derivation_event_id);
    if (existing) {
      existing.batches.push(event.batch);
    } else {
      groups.set(event.derivation_event_id, { kind: event.derivation_kind, batches: [event.batch] });
    }
  }
  return [...groups.values()];
}

function BatchLinkList({ farmId, batches }: { farmId: string; batches: LineageEvent["batch"][] }) {
  return (
    <ul className="mt-2 space-y-1">
      {batches.map((batch) => (
        <li key={batch.id}>
          <Link
            href={`/farms/${farmId}/crop-batches/${batch.id}`}
            className="font-medium text-brand-700 hover:underline"
          >
            {batch.code}
          </Link>
        </li>
      ))}
    </ul>
  );
}

/** Operational storytelling, not a schema-shaped "Parents / Children"
 * list -- this batch's own ancestry ("Created from X via split") and, if
 * this batch was itself split/merged into others, that outcome too
 * ("This batch was split into: A, B"). Technical derivation metadata
 * (event id, per-line quantities) is deliberately not surfaced here --
 * CMP has no authoritative quantity model yet, and the event id is not
 * operator-meaningful. */
export function OriginAndSplitsPanel({ lineage, farmId }: { lineage: BatchLineageRead; farmId: string }) {
  if (lineage.parents.length === 0 && lineage.children.length === 0) {
    return (
      <EmptyState
        title="No recorded origin or split relationships"
        description="This batch was not created from another batch, and has not been split or merged into others."
      />
    );
  }

  const originGroups = groupByDerivationEvent(lineage.parents);
  const outcomeGroups = groupByDerivationEvent(lineage.children);

  return (
    <div className="space-y-6">
      {originGroups.map((group, index) => (
        <div key={index} className="rounded-md border border-border-subtle p-4">
          {group.kind === "merge" ? (
            <>
              <p className="text-sm text-ink">
                Created by merging {group.batches.length} batches via {lowerFirst(humanizeEnumCode(group.kind))}:
              </p>
              <BatchLinkList farmId={farmId} batches={group.batches} />
            </>
          ) : (
            <p className="text-sm text-ink">
              Created from{" "}
              <Link
                href={`/farms/${farmId}/crop-batches/${group.batches[0].id}`}
                className="font-medium text-brand-700 hover:underline"
              >
                {group.batches[0].code}
              </Link>{" "}
              via {lowerFirst(humanizeEnumCode(group.kind))}.
            </p>
          )}
        </div>
      ))}

      {outcomeGroups.map((group, index) => (
        <div key={index} className="rounded-md border border-border-subtle p-4">
          <p className="text-sm text-ink">
            This batch was {group.kind === "split" ? "split" : lowerFirst(humanizeEnumCode(group.kind))} into:
          </p>
          <BatchLinkList farmId={farmId} batches={group.batches} />
        </div>
      ))}
    </div>
  );
}
