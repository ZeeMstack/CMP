"use client";

import type { LocationTreeNode } from "@/lib/api/client";

function flatten(nodes: LocationTreeNode[], pathPrefix: string[] = []): { id: string; label: string }[] {
  return nodes.flatMap((node) => {
    const path = [...pathPrefix, node.name];
    const self = node.occupiable === false && node.children.length === 0 ? [] : [{ id: node.id, label: path.join(" / ") }];
    return [...self, ...flatten(node.children, path)];
  });
}

/** POSTHARVEST-OPS-001G: a flat picker over the Farm's Location tree, for
 * commands that reference a single Location by id (e.g. Grading's
 * `processing_hall_location_id`, a Finished Goods Storage Movement's
 * destination). No dedicated "Processing Hall" Location classification
 * exists in the API, so every occupiable-or-branch node is offered here --
 * narrower than the full tree would be pointless without a backend filter
 * this ticket has no grounds to invent. */
export function LocationSelect({
  nodes,
  value,
  onChange,
  disabled,
  id,
}: {
  nodes: LocationTreeNode[];
  value: string;
  onChange: (locationId: string) => void;
  disabled?: boolean;
  id?: string;
}) {
  const options = flatten(nodes);
  return (
    <select
      id={id}
      value={value}
      disabled={disabled}
      onChange={(e) => onChange(e.target.value)}
      className="min-h-11 w-full rounded-md border border-border-subtle bg-surface px-3 text-sm text-ink focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-600"
    >
      <option value="">Select a location…</option>
      {options.map((opt) => (
        <option key={opt.id} value={opt.id}>
          {opt.label}
        </option>
      ))}
    </select>
  );
}
