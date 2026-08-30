import type { LocationTreeNode } from "@/lib/api/client";

export interface FlattenedLocationOption {
  id: string;
  label: string;
  depth: number;
}

/** PILOT-SETUP-001B5: flattens the already-loaded Location tree (no second
 * request -- there is no flat `GET /locations` list endpoint) into an
 * ordered, indented option list for a parent-location picker. Depth is
 * conveyed via a leading indent in the label, not a separate column, so it
 * renders correctly in a plain `<select>`. */
export function flattenLocationTree(nodes: LocationTreeNode[], depth = 0): FlattenedLocationOption[] {
  const result: FlattenedLocationOption[] = [];
  for (const node of nodes) {
    result.push({ id: node.id, label: `${"  ".repeat(depth)}${node.name} (${node.code})`, depth });
    if (node.children.length > 0) {
      result.push(...flattenLocationTree(node.children, depth + 1));
    }
  }
  return result;
}
