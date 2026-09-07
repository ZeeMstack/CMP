import type { LocationTreeNode } from "@/lib/api/client";

/** STORE-INV-002B: every active `store_bin` in a Farm's location tree,
 * labeled with its full ancestor path (e.g. "Nutrient Store / Rack A / Bin
 * 01") -- built client-side from the tree the Setup workspace already
 * fetches, never a new backend path-computation endpoint. Shared by the
 * Putaway page and the Inventory page's "Move stock" action. */
export function activeBinsWithPaths(nodes: LocationTreeNode[], prefix: string[] = []): { id: string; label: string }[] {
  const out: { id: string; label: string }[] = [];
  for (const node of nodes) {
    const path = [...prefix, node.name];
    if (node.location_type_code === "store_bin" && node.status === "active") {
      out.push({ id: node.id, label: path.join(" / ") });
    }
    out.push(...activeBinsWithPaths(node.children, path));
  }
  return out;
}
