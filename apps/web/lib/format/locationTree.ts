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

export interface FlattenedLocationCapacityOption extends FlattenedLocationOption {
  code: string;
  name: string;
  status: string;
  occupiable: boolean;
  /** Authoritative capacity per DOMAIN-FARM-002/PILOT-PLAN-001A -- `null`
   * means UNKNOWN (not configured), never "unlimited". See
   * `capacity_plan_service._effective_capacity` for the same NULL-means-1
   * default when `occupiable` and no explicit value is set. */
  capacity: number | null;
}

/** PILOT-PLAN-001B: same flattening as `flattenLocationTree`, but keeping
 * `capacity`/`occupiable` so a Capacity Allocation location picker (and the
 * Capacity Outlook worksheet's "add a location" control) can show which
 * candidate Locations already carry an authoritative capacity fact, rather
 * than re-fetching the tree a second time with a different shape. Additive
 * -- does not change `flattenLocationTree`'s own existing output/callers. */
export function flattenLocationCapacityOptions(
  nodes: LocationTreeNode[],
  depth = 0,
): FlattenedLocationCapacityOption[] {
  const result: FlattenedLocationCapacityOption[] = [];
  for (const node of nodes) {
    result.push({
      id: node.id,
      code: node.code,
      name: node.name,
      status: node.status,
      occupiable: node.occupiable,
      capacity: node.capacity,
      label: `${"  ".repeat(depth)}${node.name} (${node.code})`,
      depth,
    });
    if (node.children.length > 0) {
      result.push(...flattenLocationCapacityOptions(node.children, depth + 1));
    }
  }
  return result;
}
