"use client";

import { PlusCircle } from "lucide-react";
import { useState } from "react";

import { Breadcrumbs } from "@/components/Breadcrumbs";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { InventoryItemEditForm, InventoryItemForm } from "@/components/inventory-items/InventoryItemForm";
import { LoadingSkeleton } from "@/components/LoadingSkeleton";
import { PageHeader } from "@/components/PageHeader";
import { StandaloneShell } from "@/components/StandaloneShell";
import { StatusBadge, type StatusTone } from "@/components/StatusBadge";
import { Button } from "@/components/ui/Button";
import type { InventoryItemCreate, InventoryItemRead, InventoryItemUpdate } from "@/lib/api/client";
import { AppError } from "@/lib/errors/adapter";
import {
  useCreateInventoryItem,
  useDeactivateInventoryItem,
  useInventoryCategories,
  useInventoryItems,
  useReactivateInventoryItem,
  useUoms,
  useUpdateInventoryItem,
} from "@/lib/query/hooks";

function errorMessage(error: unknown): string {
  return error instanceof AppError ? error.message : "Something went wrong. Please try again.";
}

export default function InventoryItemsPage() {
  const [creating, setCreating] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [serverError, setServerError] = useState<string | null>(null);
  const [listActionError, setListActionError] = useState<string | null>(null);

  const itemsQuery = useInventoryItems();
  const categoriesQuery = useInventoryCategories();
  const uomsQuery = useUoms();
  const createMutation = useCreateInventoryItem();
  const updateMutation = useUpdateInventoryItem();
  const deactivateMutation = useDeactivateInventoryItem();
  const reactivateMutation = useReactivateInventoryItem();

  const items = itemsQuery.data ?? [];
  const categories = categoriesQuery.data ?? [];
  const uoms = uomsQuery.data ?? [];
  const categoryById = new Map(categories.map((c) => [c.id, c]));
  const uomById = new Map(uoms.map((u) => [u.id, u]));
  const referenceDataReady = !categoriesQuery.isLoading && !uomsQuery.isLoading;

  // docs/domain/STORE_INVENTORY_MODEL.md §5: a NEW assignment (create, or
  // reassigning an existing item) requires an active category, but an item
  // already assigned to a category that has since gone inactive keeps that
  // assignment -- so its own current (now-inactive) category must still be
  // shown as a selectable option in ITS OWN edit form (never disappearing
  // its label), while staying absent from every other picker (create, and
  // every other item's edit form).
  const activeCategories = categories.filter((c) => c.status === "active");

  function handleCreate(payload: InventoryItemCreate) {
    setServerError(null);
    createMutation.mutate(payload, {
      onSuccess: () => setCreating(false),
      onError: (error) => setServerError(errorMessage(error)),
    });
  }

  function handleUpdate(itemId: string, payload: InventoryItemUpdate) {
    setServerError(null);
    updateMutation.mutate(
      { itemId, payload },
      {
        onSuccess: () => setEditingId(null),
        onError: (error) => setServerError(errorMessage(error)),
      },
    );
  }

  const editingItem: InventoryItemRead | undefined = items.find((i) => i.id === editingId);
  const editingItemCurrentCategory = editingItem ? categoryById.get(editingItem.inventory_category_id) : undefined;
  const editFormCategories =
    editingItemCurrentCategory && editingItemCurrentCategory.status !== "active"
      ? [...activeCategories, editingItemCurrentCategory]
      : activeCategories;

  return (
    <StandaloneShell>
      <PageHeader
        title="Inventory Items"
        breadcrumbs={<Breadcrumbs items={[{ label: "Home", href: "/farms" }, { label: "Inventory Items" }]} />}
        actions={
          !creating && !editingId && referenceDataReady && activeCategories.length > 0 && (
            <Button variant="primary" onClick={() => setCreating(true)}>
              <PlusCircle aria-hidden="true" className="h-4 w-4" />
              New item
            </Button>
          )
        }
      />
      <p className="-mt-3 mb-6 text-xs text-ink-muted">
        Tenant-wide consumable-material master data, reusable across every Farm. No lot, ledger, or stock balance
        exists yet -- that begins with Goods Receipt.
      </p>

      {referenceDataReady && activeCategories.length === 0 && !creating && (
        <EmptyState
          title="No active Inventory Categories"
          description="Create or reactivate at least one active Inventory Category before configuring Inventory Items."
        />
      )}

      {creating && (
        <InventoryItemForm
          categories={activeCategories}
          uoms={uoms}
          isSubmitting={createMutation.isPending}
          serverError={serverError}
          onCancel={() => {
            setCreating(false);
            setServerError(null);
          }}
          onSubmit={handleCreate}
        />
      )}

      {editingItem && (
        <InventoryItemEditForm
          item={editingItem}
          categories={editFormCategories}
          uoms={uoms}
          isSubmitting={updateMutation.isPending}
          serverError={serverError}
          onCancel={() => {
            setEditingId(null);
            setServerError(null);
          }}
          onSubmit={(payload) => handleUpdate(editingItem.id, payload)}
        />
      )}

      {!creating && !editingId && (
        <>
          {itemsQuery.isLoading && <LoadingSkeleton rows={4} label="Loading inventory items" />}
          {itemsQuery.error && <ErrorState error={itemsQuery.error} onRetry={() => itemsQuery.refetch()} />}
          {listActionError && (
            <p role="alert" className="mb-4 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
              {listActionError}
            </p>
          )}
          {!itemsQuery.isLoading && !itemsQuery.error && items.length === 0 && categories.length > 0 && (
            <EmptyState
              title="No inventory items yet"
              description="Create the first consumable-material master record."
            />
          )}
          {!itemsQuery.isLoading && !itemsQuery.error && items.length > 0 && (
            <div className="overflow-x-auto rounded-xl border border-border-subtle bg-surface">
              <table className="w-full text-left text-sm">
                <thead className="border-b border-border-subtle bg-surface-subtle text-xs uppercase text-ink-muted">
                  <tr>
                    <th className="px-4 py-2 font-medium">Code</th>
                    <th className="px-4 py-2 font-medium">Name</th>
                    <th className="px-4 py-2 font-medium">Category</th>
                    <th className="px-4 py-2 font-medium">Base UOM</th>
                    <th className="px-4 py-2 font-medium">Tracking</th>
                    <th className="px-4 py-2 font-medium">Status</th>
                    <th className="px-4 py-2 font-medium" />
                  </tr>
                </thead>
                <tbody className="divide-y divide-border-subtle">
                  {items.map((item) => {
                    const tone: StatusTone = item.status === "active" ? "active" : "closed";
                    const isBusy = deactivateMutation.isPending || reactivateMutation.isPending;
                    const flags = [
                      item.lot_tracking_required && "Lot",
                      item.expiry_tracking_required && "Expiry",
                      item.qc_release_required && "QC",
                    ].filter(Boolean);
                    return (
                      <tr key={item.id} className="hover:bg-surface-subtle">
                        <td className="px-4 py-2 font-medium text-ink">{item.code}</td>
                        <td className="px-4 py-2 text-ink">{item.name}</td>
                        <td className="px-4 py-2 text-ink">{categoryById.get(item.inventory_category_id)?.name ?? "—"}</td>
                        <td className="px-4 py-2 text-ink">{uomById.get(item.base_uom_id)?.code ?? "—"}</td>
                        <td className="px-4 py-2 text-xs text-ink-muted">{flags.length ? flags.join(", ") : "—"}</td>
                        <td className="px-4 py-2">
                          <StatusBadge label={item.status === "active" ? "Active" : "Inactive"} tone={tone} />
                        </td>
                        <td className="px-4 py-2">
                          <div className="flex gap-2">
                            <Button variant="secondary" disabled={isBusy} onClick={() => setEditingId(item.id)}>
                              Edit
                            </Button>
                            {item.status === "active" ? (
                              <Button
                                variant="secondary"
                                disabled={isBusy}
                                onClick={() => {
                                  setListActionError(null);
                                  deactivateMutation.mutate(
                                    { itemId: item.id, payload: { client_command_id: crypto.randomUUID() } },
                                    { onError: (error) => setListActionError(errorMessage(error)) },
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
                                  setListActionError(null);
                                  reactivateMutation.mutate(
                                    { itemId: item.id, payload: { client_command_id: crypto.randomUUID() } },
                                    { onError: (error) => setListActionError(errorMessage(error)) },
                                  );
                                }}
                              >
                                Reactivate
                              </Button>
                            )}
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </StandaloneShell>
  );
}
