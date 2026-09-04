"use client";

import type { LocationTreeNode } from "@/lib/api/client";
import { STORE_TYPE_LABELS, type StoreTypeCode } from "@/lib/format/storeTree";

/** A simple, purpose-built recursive renderer for Store-rooted subtrees --
 * deliberately not `LocationTree` (which is built around live occupancy
 * display, irrelevant here: nothing may occupy a Store Bin yet, that is
 * STORE-INV-005 scope, see docs/domain/STORE_INVENTORY_MODEL.md §12). */
function StoreNodeRow({ node, depth }: { node: LocationTreeNode; depth: number }) {
  const typeCode = node.location_type_code as StoreTypeCode;
  return (
    <div>
      <div
        className="flex items-center gap-2 rounded-md px-2 py-1.5 hover:bg-surface-subtle"
        style={{ paddingLeft: `${depth * 1.25 + 0.5}rem` }}
      >
        <span className="text-sm font-medium text-ink">{node.name}</span>
        <span className="text-xs text-ink-muted">({node.code})</span>
        <span className="rounded-full bg-surface-subtle px-2 py-0.5 text-xs text-ink-muted">
          {STORE_TYPE_LABELS[typeCode] ?? typeCode}
        </span>
      </div>
      {node.children.length > 0 && (
        <div>
          {(node.children as LocationTreeNode[]).map((child) => (
            <StoreNodeRow key={child.id} node={child} depth={depth + 1} />
          ))}
        </div>
      )}
    </div>
  );
}

export function StoreTreeView({ storeRoots }: { storeRoots: LocationTreeNode[] }) {
  return (
    <div className="rounded-xl border border-border-subtle bg-surface p-2">
      {storeRoots.map((root) => (
        <StoreNodeRow key={root.id} node={root} depth={0} />
      ))}
    </div>
  );
}
