"use client";

import { useState } from "react";

import { Button } from "@/components/ui/Button";
import { StatusBadge, type StatusTone } from "@/components/StatusBadge";
import { AppError } from "@/lib/errors/adapter";
import {
  useCreateInventoryItemPackaging,
  useDeactivateInventoryItemPackaging,
  useInventoryItemPackaging,
  useReactivateInventoryItemPackaging,
  useUpdateInventoryItemPackaging,
} from "@/lib/query/hooks";

function errorMessage(error: unknown): string {
  return error instanceof AppError ? error.message : "Something went wrong. Please try again.";
}

const inputClass =
  "h-9 w-full rounded-md border border-border-subtle bg-surface px-2 text-sm text-ink focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-600";

/** STORE-INV-002A.1: "Packaging Options" -- item-specific display/receiving
 * units (e.g. `BAG-25KG`), surfaced inside the Inventory Catalog's item
 * detail area (never a `UnitOfMeasure` -- docs/domain/
 * STORE_INVENTORY_MODEL.md §5/§L). `package_quantity` structurally freezes
 * once any Goods Receipt line references it -- the update form still lets
 * `display_name` through even after that point, and surfaces the backend's
 * own lock error plainly rather than guessing when it will fire. */
export function PackagingOptionsPanel({ itemId, baseUomCode }: { itemId: string; baseUomCode: string }) {
  const [adding, setAdding] = useState(false);
  const [code, setCode] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [quantity, setQuantity] = useState("");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editDisplayName, setEditDisplayName] = useState("");
  const [editQuantity, setEditQuantity] = useState("");
  const [formError, setFormError] = useState<string | null>(null);
  const [rowError, setRowError] = useState<string | null>(null);

  const packagingQuery = useInventoryItemPackaging({ inventoryItemId: itemId });
  const createMutation = useCreateInventoryItemPackaging();
  const updateMutation = useUpdateInventoryItemPackaging();
  const deactivateMutation = useDeactivateInventoryItemPackaging();
  const reactivateMutation = useReactivateInventoryItemPackaging();

  const rows = packagingQuery.data ?? [];

  function resetAddForm() {
    setAdding(false);
    setCode("");
    setDisplayName("");
    setQuantity("");
    setFormError(null);
  }

  function handleAdd() {
    setFormError(null);
    if (!code.trim() || !displayName.trim() || !quantity.trim()) {
      setFormError("Code, display name, and quantity are all required.");
      return;
    }
    const parsed = Number(quantity);
    if (!Number.isFinite(parsed) || parsed <= 0) {
      setFormError("Quantity must be a positive number.");
      return;
    }
    createMutation.mutate(
      {
        client_command_id: crypto.randomUUID(),
        inventory_item_id: itemId,
        code: code.trim(),
        display_name: displayName.trim(),
        package_quantity: quantity.trim(),
      },
      { onSuccess: () => resetAddForm(), onError: (error) => setFormError(errorMessage(error)) },
    );
  }

  function startEdit(row: { id: string; display_name: string; package_quantity: string }) {
    setEditingId(row.id);
    setEditDisplayName(row.display_name);
    setEditQuantity(String(row.package_quantity));
    setRowError(null);
  }

  function handleSaveEdit(packagingId: string) {
    setRowError(null);
    if (!editDisplayName.trim() || !editQuantity.trim()) {
      setRowError("Display name and quantity are required.");
      return;
    }
    updateMutation.mutate(
      { packagingId, payload: { client_command_id: crypto.randomUUID(), display_name: editDisplayName.trim(), package_quantity: editQuantity.trim() } },
      { onSuccess: () => setEditingId(null), onError: (error) => setRowError(errorMessage(error)) },
    );
  }

  return (
    <div className="mt-4 rounded-xl border border-border-subtle bg-surface p-4">
      <div className="mb-2 flex items-center justify-between">
        <h4 className="text-sm font-semibold text-ink">Packaging Options</h4>
        {!adding && (
          <Button variant="secondary" onClick={() => setAdding(true)}>
            Add packaging
          </Button>
        )}
      </div>
      <p className="mb-3 text-xs text-ink-muted">
        Display/receiving units for this item (e.g. a 25kg bag) -- never a Unit of Measure. Quantity is always
        expressed in this item&apos;s base UOM ({baseUomCode}).
      </p>

      {adding && (
        <div className="mb-3 flex flex-wrap items-end gap-2 rounded-md border border-border-subtle p-3">
          <label className="flex flex-col gap-1 text-xs text-ink-muted">
            Code
            <input className={inputClass} value={code} onChange={(e) => setCode(e.target.value)} placeholder="BAG-25KG" />
          </label>
          <label className="flex flex-col gap-1 text-xs text-ink-muted">
            Display name
            <input className={inputClass} value={displayName} onChange={(e) => setDisplayName(e.target.value)} placeholder="25kg Bag" />
          </label>
          <label className="flex flex-col gap-1 text-xs text-ink-muted">
            Quantity ({baseUomCode})
            <input className={inputClass} value={quantity} onChange={(e) => setQuantity(e.target.value)} placeholder="25" />
          </label>
          <Button variant="primary" disabled={createMutation.isPending} onClick={handleAdd}>
            Save
          </Button>
          <Button variant="secondary" onClick={resetAddForm}>
            Cancel
          </Button>
          {formError && <p className="w-full text-xs text-red-700">{formError}</p>}
        </div>
      )}

      {rowError && <p className="mb-2 text-xs text-red-700">{rowError}</p>}

      {packagingQuery.isLoading && <p className="text-xs text-ink-muted">Loading packaging options…</p>}
      {!packagingQuery.isLoading && rows.length === 0 && (
        <p className="text-xs text-ink-muted">No packaging options configured for this item yet.</p>
      )}
      {rows.length > 0 && (
        <table className="w-full text-left text-sm">
          <thead className="text-xs uppercase text-ink-muted">
            <tr>
              <th className="py-1 pr-2 font-medium">Code</th>
              <th className="py-1 pr-2 font-medium">Display Name</th>
              <th className="py-1 pr-2 font-medium">Quantity</th>
              <th className="py-1 pr-2 font-medium">Status</th>
              <th className="py-1 font-medium" />
            </tr>
          </thead>
          <tbody className="divide-y divide-border-subtle">
            {rows.map((row) => {
              const tone: StatusTone = row.status === "active" ? "active" : "closed";
              const isEditing = editingId === row.id;
              const isBusy = updateMutation.isPending || deactivateMutation.isPending || reactivateMutation.isPending;
              return (
                <tr key={row.id}>
                  <td className="py-1.5 pr-2 font-medium text-ink">{row.code}</td>
                  <td className="py-1.5 pr-2">
                    {isEditing ? (
                      <input className={inputClass} value={editDisplayName} onChange={(e) => setEditDisplayName(e.target.value)} />
                    ) : (
                      row.display_name
                    )}
                  </td>
                  <td className="py-1.5 pr-2">
                    {isEditing ? (
                      <input className={inputClass} value={editQuantity} onChange={(e) => setEditQuantity(e.target.value)} />
                    ) : (
                      `${row.package_quantity} ${baseUomCode}`
                    )}
                  </td>
                  <td className="py-1.5 pr-2">
                    <StatusBadge label={row.status === "active" ? "Active" : "Inactive"} tone={tone} />
                  </td>
                  <td className="py-1.5">
                    <div className="flex gap-2">
                      {isEditing ? (
                        <>
                          <Button variant="secondary" disabled={isBusy} onClick={() => handleSaveEdit(row.id)}>
                            Save
                          </Button>
                          <Button variant="secondary" onClick={() => setEditingId(null)}>
                            Cancel
                          </Button>
                        </>
                      ) : (
                        <>
                          <Button variant="secondary" disabled={isBusy} onClick={() => startEdit(row)}>
                            Edit
                          </Button>
                          {row.status === "active" ? (
                            <Button
                              variant="secondary"
                              disabled={isBusy}
                              onClick={() => {
                                setRowError(null);
                                deactivateMutation.mutate(
                                  { packagingId: row.id, payload: { client_command_id: crypto.randomUUID() } },
                                  { onError: (error) => setRowError(errorMessage(error)) },
                                );
                              }}
                            >
                              Deactivate
                            </Button>
                          ) : (
                            <Button
                              variant="secondary"
                              disabled={isBusy}
                              onClick={() => {
                                setRowError(null);
                                reactivateMutation.mutate(
                                  { packagingId: row.id, payload: { client_command_id: crypto.randomUUID() } },
                                  { onError: (error) => setRowError(errorMessage(error)) },
                                );
                              }}
                            >
                              Reactivate
                            </Button>
                          )}
                        </>
                      )}
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </div>
  );
}
