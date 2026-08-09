"use client";

import { ChevronRight } from "lucide-react";
import { useState } from "react";

import { StatusBadge } from "@/components/StatusBadge";
import type { LocationTreeNode } from "@/lib/api/client";
import { useLocationOccupant } from "@/lib/query/hooks";

function OccupantBadge({ farmId, locationId, occupiable }: { farmId: string; locationId: string; occupiable: boolean }) {
  // Fetched only once this node's occupancy has actually been requested --
  // never eagerly for the whole tree.
  const [requested, setRequested] = useState(false);
  const { data, isLoading } = useLocationOccupant(farmId, locationId, requested);

  if (!occupiable) return null;

  if (!requested) {
    return (
      <button
        type="button"
        onClick={() => setRequested(true)}
        className="min-h-8 rounded-md px-2 text-xs font-medium text-brand-700 hover:bg-brand-50"
      >
        Check occupancy
      </button>
    );
  }
  if (isLoading) return <span className="text-xs text-ink-muted">Checking…</span>;
  if (data?.active_occupancy) {
    return <StatusBadge label={`Occupied (${data.active_occupancy.occupant.kind})`} tone="active" />;
  }
  return <StatusBadge label="Empty" tone="neutral" />;
}

function TreeNode({ node, farmId, depth }: { node: LocationTreeNode; farmId: string; depth: number }) {
  const [expanded, setExpanded] = useState(depth < 1);
  const hasChildren = node.children.length > 0;

  return (
    <li>
      <div className="flex min-h-11 items-center gap-2 py-1" style={{ paddingLeft: depth * 16 }}>
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
        <span className="truncate text-sm font-medium text-ink">{node.name}</span>
        <span className="shrink-0 text-xs text-ink-muted">{node.code}</span>
        {node.status !== "active" && <StatusBadge label={node.status} tone="closed" />}
        <span className="ml-auto shrink-0">
          <OccupantBadge farmId={farmId} locationId={node.id} occupiable={node.occupiable} />
        </span>
      </div>
      {hasChildren && expanded && (
        <ul>
          {node.children.map((child) => (
            <TreeNode key={child.id} node={child} farmId={farmId} depth={depth + 1} />
          ))}
        </ul>
      )}
    </li>
  );
}

/** Renders the farm's location hierarchy exactly as returned -- no assumed
 * fixed depth (greenhouse/zone/span/table). */
export function LocationTree({ nodes, farmId }: { nodes: LocationTreeNode[]; farmId: string }) {
  return (
    <ul role="tree" aria-label="Locations" className="divide-y divide-border-subtle">
      {nodes.map((node) => (
        <TreeNode key={node.id} node={node} farmId={farmId} depth={0} />
      ))}
    </ul>
  );
}
