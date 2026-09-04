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
  status: string;
}

/** Flattens Store-rooted subtrees only, for parent pickers -- mirrors
 * `flattenLocationTree` but scoped and type-labeled. Carries `status` so
 * callers can exclude inactive parents from create selectors (UX-IA-001,
 * docs/domain/STORE_INVENTORY_MODEL.md §19 "Inactive parents excluded from
 * Storage child-create choices") -- the backend remains independently
 * authoritative via `InactiveParentLocationError`; this only prevents
 * offering a known-invalid choice in the first place. */
export function flattenStoreTree(nodes: LocationTreeNode[], depth = 0): FlattenedStoreOption[] {
  const result: FlattenedStoreOption[] = [];
  for (const node of nodes) {
    const typeCode = node.location_type_code as StoreTypeCode;
    result.push({
      id: node.id,
      label: `${"  ".repeat(depth)}${node.name} (${node.code}) — ${STORE_TYPE_LABELS[typeCode] ?? typeCode}`,
      typeCode,
      depth,
      status: node.status,
    });
    if (node.children.length > 0) {
      result.push(...flattenStoreTree(node.children as LocationTreeNode[], depth + 1));
    }
  }
  return result;
}

/** Active-only parent choices -- the actual selector filter UX-IA-001
 * applies on top of `flattenStoreTree`'s full (status-agnostic) output. */
export function activeOnly(options: FlattenedStoreOption[]): FlattenedStoreOption[] {
  return options.filter((o) => o.status === "active");
}

export interface StoreHierarchyCounts {
  activeStores: number;
  totalStores: number;
  areas: number;
  racks: number;
  bins: number;
}

/** Setup Summary counts (docs/domain/STORE_INVENTORY_MODEL.md §19) --
 * `activeStores` gates the Storage card's empty state (a farm with only
 * deactivated Stores is not "configured"); Areas/Racks/Bins are counted
 * regardless of status, matching the Overview's own framing of showing
 * what exists, not a second active/inactive breakdown the Storage view
 * itself already shows per row. */
export function countStoreHierarchy(storeRoots: LocationTreeNode[]): StoreHierarchyCounts {
  const counts: StoreHierarchyCounts = { activeStores: 0, totalStores: 0, areas: 0, racks: 0, bins: 0 };

  function walk(nodes: LocationTreeNode[]) {
    for (const node of nodes) {
      switch (node.location_type_code as StoreTypeCode) {
        case "store_area":
          counts.areas += 1;
          break;
        case "store_rack":
          counts.racks += 1;
          break;
        case "store_bin":
          counts.bins += 1;
          break;
      }
      walk(node.children as LocationTreeNode[]);
    }
  }

  for (const store of storeRoots) {
    counts.totalStores += 1;
    if (store.status === "active") counts.activeStores += 1;
  }
  walk(storeRoots);
  return counts;
}
