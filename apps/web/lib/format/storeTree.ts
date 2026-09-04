import type { LocationTreeNode } from "@/lib/api/client";

export const STORE_TYPE_CODES = ["store", "store_area", "store_rack", "store_bin"] as const;
export type StoreTypeCode = (typeof STORE_TYPE_CODES)[number];

export const STORE_TYPE_LABELS: Record<StoreTypeCode, string> = {
  store: "Store",
  store_area: "Area",
  store_rack: "Rack",
  store_bin: "Bin",
};

/** docs/domain/STORE_INVENTORY_MODEL.md §4/§9: Store and Greenhouse are
 * never presented as one undifferentiated setup workflow -- this filters
 * the full farm tree (already fetched for the generic Locations page) down
 * to just the root `store` subtrees, reusing `location_type_code`
 * (STORE-INV-001B) rather than a second fetch. */
export function extractStoreRoots(tree: LocationTreeNode[]): LocationTreeNode[] {
  return tree.filter((node) => node.location_type_code === "store");
}

export interface FlattenedStoreOption {
  id: string;
  label: string;
  typeCode: StoreTypeCode;
  depth: number;
}

/** Flattens Store-rooted subtrees only, for parent pickers -- mirrors
 * `flattenLocationTree` but scoped and type-labeled. */
export function flattenStoreTree(nodes: LocationTreeNode[], depth = 0): FlattenedStoreOption[] {
  const result: FlattenedStoreOption[] = [];
  for (const node of nodes) {
    const typeCode = node.location_type_code as StoreTypeCode;
    result.push({
      id: node.id,
      label: `${"  ".repeat(depth)}${node.name} (${node.code}) — ${STORE_TYPE_LABELS[typeCode] ?? typeCode}`,
      typeCode,
      depth,
    });
    if (node.children.length > 0) {
      result.push(...flattenStoreTree(node.children as LocationTreeNode[], depth + 1));
    }
  }
  return result;
}
