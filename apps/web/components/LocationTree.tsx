"use client";

import { ChevronRight } from "lucide-react";
import { useMemo, useState } from "react";

import { StatusBadge } from "@/components/StatusBadge";
import type { LocationAggregateCount, LocationTreeNode as LocationTreeNodeType, OccupiedLocation } from "@/lib/api/client";
import { useLocationSubtreeOccupancy } from "@/lib/query/hooks";

type OccupancyLookup = {
  aggregateByLocationId: Map<string, LocationAggregateCount>;
  occupiedByLocationId: Map<string, OccupiedLocation>;
};

function AggregateCountLabel({ aggregate }: { aggregate: LocationAggregateCount | undefined }) {
  if (!aggregate) return null;
  return (
    <span className="shrink-0 text-xs text-ink-muted">
      {aggregate.occupied_location_count} / {aggregate.occupiable_location_count} occupied
    </span>
  );
}

/** Occupant detail rendered inline in the tree row -- no click required.
 * Batch code/crop/stage are the operationally useful facts and stay
 * prominent; the carrier code is a secondary identifier, shown muted. */
function OccupancyDetail({
  node,
  occupancy,
  loading,
}: {
  node: LocationTreeNodeType;
  occupancy: OccupancyLookup | null;
  loading: boolean;
}) {
  if (!node.occupiable) return null;
  if (!occupancy) {
    return <span className="text-xs text-ink-muted">{loading ? "Loading…" : ""}</span>;
  }
  const occupied = occupancy.occupiedByLocationId.get(node.id);
  if (!occupied) {
    return <StatusBadge label="Empty" tone="neutral" />;
  }
  const batch = occupied.occupant.batch;
  return (
    <span className="flex flex-col items-start gap-0.5 text-xs sm:flex-row sm:items-center sm:gap-2">
      {batch ? (
        <span className="text-ink">
          <span className="font-medium">{batch.batch_code}</span> · {batch.crop.common_name} ·{" "}
          {batch.current_stage.name}
        </span>
      ) : (
        <span className="text-ink-muted">Occupied (no batch assigned)</span>
      )}
      {occupied.occupant.carrier_code && <span className="text-ink-muted">{occupied.occupant.carrier_code}</span>}
    </span>
  );
}

function TreeNode({
  node,
  farmId,
  depth,
  occupancy,
}: {
  node: LocationTreeNodeType;
  farmId: string;
  depth: number;
  occupancy: OccupancyLookup | null;
}) {
  const [expanded, setExpanded] = useState(depth < 1);
  const hasChildren = node.children.length > 0;

  // Only a genuine root branch (depth 0, no ancestor already providing
  // occupancy) issues its own subtree-occupancy request -- one request per
  // independently-expanded top-level branch, never one per child/leaf.
  // Descendants receive the already-loaded lookup as a prop; expanding a
  // deeper node (a zone, a table) never triggers a second fetch, since its
  // facts were already included in the ancestor's subtree response.
  const isRoot = depth === 0;
  const subtreeQuery = useLocationSubtreeOccupancy(farmId, node.id, isRoot && expanded);

  const rootOccupancy: OccupancyLookup | null = useMemo(() => {
    if (!isRoot || !subtreeQuery.data) return null;
    return {
      aggregateByLocationId: new Map(subtreeQuery.data.aggregate_counts.map((a) => [a.location_id, a])),
      occupiedByLocationId: new Map(subtreeQuery.data.occupied_locations.map((o) => [o.location_id, o])),
    };
  }, [isRoot, subtreeQuery.data]);

  const resolvedOccupancy = isRoot ? rootOccupancy : occupancy;
  const aggregate = resolvedOccupancy?.aggregateByLocationId.get(node.id);

  return (
    <li>
      <div className="flex min-h-11 flex-wrap items-center gap-x-2 gap-y-1 py-1" style={{ paddingLeft: depth * 16 }}>
        {hasChildren ? (
          <button
            type="button"
            onClick={() => setExpanded((v) => !v)}
            aria-expanded={expanded}
            aria-label={`${expanded ? "Collapse" : "Expand"} ${node.name}`}
            className="flex h-6 w-6 shrink-0 items-center justify-center rounded hover:bg-surface-subtle"
          >
            <ChevronRight
              aria-hidden="true"
              className={`h-4 w-4 transition-transform ${expanded ? "rotate-90" : ""}`}
            />
          </button>
        ) : (
          <span className="w-6 shrink-0" />
        )}
        {/* Human name is primary; the technical code is a secondary, muted
            identifier next to it -- never repeated with equal emphasis. */}
        <span className="truncate text-sm font-medium text-ink">{node.name}</span>
        {node.code !== node.name && <span className="shrink-0 text-xs text-ink-muted">{node.code}</span>}
        {node.capacity != null && node.capacity > 1 && (
          <span className="shrink-0 text-xs text-ink-muted">capacity {node.capacity}</span>
        )}
        {node.status !== "active" && <StatusBadge label={node.status} tone="closed" />}
        {hasChildren && <AggregateCountLabel aggregate={aggregate} />}
        {isRoot && subtreeQuery.error && (
          <span className="text-xs text-red-700">Occupancy unavailable for this branch</span>
        )}
        <span className="ml-auto shrink-0">
          <OccupancyDetail node={node} occupancy={resolvedOccupancy} loading={isRoot && subtreeQuery.isLoading} />
        </span>
      </div>
      {hasChildren && expanded && (
        <ul>
          {node.children.map((child) => (
            <TreeNode key={child.id} node={child} farmId={farmId} depth={depth + 1} occupancy={resolvedOccupancy} />
          ))}
        </ul>
      )}
    </li>
  );
}

/** Renders the farm's location hierarchy exactly as returned -- no assumed
 * fixed depth (greenhouse/zone/span/table). Occupancy facts are fetched
 * once per expanded top-level branch (see TreeNode) and merged onto this
 * already-loaded structure client-side; there is no per-leaf "check
 * occupancy" interaction. */
export function LocationTree({ nodes, farmId }: { nodes: LocationTreeNodeType[]; farmId: string }) {
  return (
    <ul role="tree" aria-label="Locations" className="divide-y divide-border-subtle">
      {nodes.map((node) => (
        <TreeNode key={node.id} node={node} farmId={farmId} depth={0} occupancy={null} />
      ))}
    </ul>
  );
}
