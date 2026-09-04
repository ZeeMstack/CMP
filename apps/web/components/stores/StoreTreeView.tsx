"use client";

import { useState } from "react";

import { StatusBadge } from "@/components/StatusBadge";
import { Button } from "@/components/ui/Button";
import type { LocationTreeNode } from "@/lib/api/client";
import { STORE_TYPE_LABELS, type StoreTypeCode } from "@/lib/format/storeTree";

const inputClass =
  "min-h-8 rounded-md border border-border-subtle bg-surface px-2 text-sm text-ink focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-600";

export interface StoreRowError {
  locationId: string;
  message: string;
}

interface StoreTreeViewProps {
  storeRoots: LocationTreeNode[];
  renamingId: string | null;
  isMutating: boolean;
  rowError: StoreRowError | null;
  onStartRename: (locationId: string) => void;
  onCancelRename: () => void;
  onRename: (locationId: string, name: string) => void;
  onDeactivate: (locationId: string) => void;
  onReactivate: (locationId: string) => void;
}

/** UX-IA-001: inline rename, matching `InventoryCategoriesPage`'s own
 * `RenameRow` shape -- code is never editable anywhere, communicated here
 * rather than merely omitted. */
function RenameRow({
  node,
  onCancel,
  onSave,
  isSaving,
}: {
  node: LocationTreeNode;
  onCancel: () => void;
  onSave: (name: string) => void;
  isSaving: boolean;
}) {
  const [name, setName] = useState(node.name);
  return (
    <div className="flex flex-wrap items-center gap-2">
      <input
        className={inputClass}
        value={name}
        onChange={(e) => setName(e.target.value)}
        aria-label={`Rename ${node.code}`}
      />
      <span className="text-xs text-ink-muted" title="Code cannot be changed because it identifies this location.">
        Code {node.code} — locked
      </span>
      <Button variant="primary" disabled={isSaving || !name.trim()} onClick={() => onSave(name.trim())}>
        Save
      </Button>
      <Button variant="secondary" disabled={isSaving} onClick={onCancel}>
        Cancel
      </Button>
    </div>
  );
}

function StoreNodeRow({
  node,
  depth,
  renamingId,
  isMutating,
  rowError,
  onStartRename,
  onCancelRename,
  onRename,
  onDeactivate,
  onReactivate,
}: {
  node: LocationTreeNode;
  depth: number;
} & Omit<StoreTreeViewProps, "storeRoots">) {
  const typeCode = node.location_type_code as StoreTypeCode;
  const isRenaming = renamingId === node.id;
  const isActive = node.status === "active";

  return (
    <div>
      <div
        className="flex flex-wrap items-center gap-2 rounded-md px-2 py-1.5 hover:bg-surface-subtle"
        style={{ paddingLeft: `${depth * 1.25 + 0.5}rem` }}
      >
        {isRenaming ? (
          <RenameRow
            node={node}
            isSaving={isMutating}
            onCancel={onCancelRename}
            onSave={(name) => onRename(node.id, name)}
          />
        ) : (
          <>
            <span className="text-sm font-medium text-ink">{node.name}</span>
            <span className="text-xs text-ink-muted">({node.code})</span>
            <span className="rounded-full bg-surface-subtle px-2 py-0.5 text-xs text-ink-muted">
              {STORE_TYPE_LABELS[typeCode] ?? typeCode}
            </span>
            <StatusBadge label={isActive ? "Active" : "Inactive"} tone={isActive ? "active" : "closed"} />
            <div className="ml-auto flex items-center gap-2">
              <Button variant="secondary" disabled={isMutating} onClick={() => onStartRename(node.id)}>
                Edit
              </Button>
              {isActive ? (
                <Button variant="secondary" disabled={isMutating} onClick={() => onDeactivate(node.id)}>
                  Deactivate
                </Button>
              ) : (
                <Button variant="secondary" disabled={isMutating} onClick={() => onReactivate(node.id)}>
                  Reactivate
                </Button>
              )}
            </div>
          </>
        )}
      </div>
      {rowError && rowError.locationId === node.id && (
        <p
          role="alert"
          className="ml-2 mt-1 rounded-md border border-red-200 bg-red-50 px-3 py-1.5 text-xs text-red-800"
          style={{ marginLeft: `${depth * 1.25 + 0.5}rem` }}
        >
          {rowError.message}
        </p>
      )}
      {node.children.length > 0 && (
        <div>
          {(node.children as LocationTreeNode[]).map((child) => (
            <StoreNodeRow
              key={child.id}
              node={child}
              depth={depth + 1}
              renamingId={renamingId}
              isMutating={isMutating}
              rowError={rowError}
              onStartRename={onStartRename}
              onCancelRename={onCancelRename}
              onRename={onRename}
              onDeactivate={onDeactivate}
              onReactivate={onReactivate}
            />
          ))}
        </div>
      )}
    </div>
  );
}

export function StoreTreeView({ storeRoots, ...actions }: StoreTreeViewProps) {
  return (
    <div className="rounded-xl border border-border-subtle bg-surface p-2">
      {storeRoots.map((root) => (
        <StoreNodeRow key={root.id} node={root} depth={0} {...actions} />
      ))}
    </div>
  );
}
