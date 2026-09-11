"use client";

import { PlusCircle } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { InventoryItemEditForm, InventoryItemForm } from "@/components/inventory-items/InventoryItemForm";
import { PackagingOptionsPanel } from "@/components/inventory-items/PackagingOptionsPanel";
import { SeedDetailsPanel } from "@/components/inventory-items/SeedDetailsPanel";
import { LoadingSkeleton } from "@/components/LoadingSkeleton";
import { StatusBadge, type StatusTone } from "@/components/StatusBadge";
import { Button } from "@/components/ui/Button";
import {
  tableBodyDividerClass,
  tableHeadRowClass,
  tableRowHoverClass,
  tableTdClass,
  tableThClass,
  tableWrapperClass,
} from "@/components/ui/table";
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

/** UX-IA-001: the Inventory Catalog view within the Store & Inventory
 * Setup workspace -- extracted, unchanged in substance, from the
 * pre-existing `/inventory-items` page. Rendered by both that legacy route
 * and the new workspace `catalog` child route. `categoriesHref` differs by
 * caller (the standalone route links to `/inventory-categories`; the
 * workspace route links to its own `settings` view) so this component
 * never hardcodes a route that only makes sense from one context. */
export function InventoryCatalogSection({ categoriesHref }: { categoriesHref: string }) {
  const [creating, setCreating] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [detailsId, setDetailsId] = useState<string | null>(null);
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
    <div>
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs text-wl-text-secondary">
          Tenant-wide consumable-material master data, reusable across every Farm. No lot, ledger, or stock balance
          exists yet -- that begins with Goods Receipt.
        </p>
        <div className="flex shrink-0 items-center gap-2">
          <Link
            href={categoriesHref}
            className="flex h-9 items-center rounded-md border border-wl-border bg-wl-surface-raised px-3 text-sm font-medium text-wl-text hover:bg-wl-surface-sunken"
          >
            Manage categories
          </Link>
          {!creating && !editingId && referenceDataReady && activeCategories.length > 0 && (
            <Button variant="primary" onClick={() => setCreating(true)}>
              <PlusCircle aria-hidden="true" className="h-4 w-4" />
              New item
            </Button>
          )}
        </div>
      </div>

      {referenceDataReady && activeCategories.length === 0 && !creating && (
        <EmptyState
          title="No active Inventory Categories"
          description="Create or reactivate at least one active Inventory Category before configuring Inventory Items."
          action={
            <Link
              href={categoriesHref}
              className="mt-2 flex h-9 items-center gap-1.5 rounded-[7px] bg-brand-600 px-4 text-sm font-medium text-white hover:bg-brand-700"
            >
              Create / Manage Categories
            </Link>
          }
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
            <div className={tableWrapperClass}>
              <table className="w-full text-left text-sm">
                <thead>
                  <tr className={tableHeadRowClass}>
                    <th className={tableThClass}>Code</th>
                    <th className={tableThClass}>Name</th>
                    <th className={tableThClass}>Category</th>
                    <th className={tableThClass}>Base UOM</th>
                    <th className={tableThClass}>Tracking</th>
                    <th className={tableThClass}>Status</th>
                    <th className={tableThClass} />
                  </tr>
                </thead>
                <tbody className={tableBodyDividerClass}>
                  {items.map((item) => {
                    const tone: StatusTone = item.status === "active" ? "active" : "closed";
                    const isBusy = deactivateMutation.isPending || reactivateMutation.isPending;
                    const flags = [
                      item.lot_tracking_required && "Lot",
                      item.expiry_tracking_required && "Expiry",
                      item.qc_release_required && "QC",
                    ].filter(Boolean);
                    return (
                      <tr key={item.id} className={tableRowHoverClass}>
                        <td className={`${tableTdClass} font-medium text-wl-text`}>{item.code}</td>
                        <td className={`${tableTdClass} text-wl-text`}>{item.name}</td>
                        <td className={`${tableTdClass} text-wl-text`}>{categoryById.get(item.inventory_category_id)?.name ?? "—"}</td>
                        <td className={`${tableTdClass} text-wl-text`}>{uomById.get(item.base_uom_id)?.code ?? "—"}</td>
                        <td className={`${tableTdClass} text-xs text-wl-text-secondary`}>{flags.length ? flags.join(", ") : "—"}</td>
                        <td className={tableTdClass}>
                          <StatusBadge label={item.status === "active" ? "Active" : "Inactive"} tone={tone} />
                        </td>
                        <td className={tableTdClass}>
                          <div className="flex gap-2">
                            <Button variant="secondary" disabled={isBusy} onClick={() => setEditingId(item.id)}>
                              Edit
                            </Button>
                            <Button
                              variant="secondary"
                              disabled={isBusy}
                              onClick={() => setDetailsId(detailsId === item.id ? null : item.id)}
                            >
                              {detailsId === item.id ? "Hide details" : "Details"}
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
                  {detailsId &&
                    (() => {
                      const detailItem = items.find((i) => i.id === detailsId);
                      if (!detailItem) return null;
                      return (
                        <tr key={`${detailsId}-details`}>
                          <td colSpan={7} className="bg-wl-surface-sunken px-4 py-3">
                            <PackagingOptionsPanel
                              itemId={detailItem.id}
                              baseUomCode={uomById.get(detailItem.base_uom_id)?.code ?? ""}
                            />
                            <SeedDetailsPanel itemId={detailItem.id} />
                          </td>
                        </tr>
                      );
                    })()}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </div>
  );
}
