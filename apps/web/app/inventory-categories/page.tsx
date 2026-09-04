"use client";

import { PlusCircle } from "lucide-react";
import { useState } from "react";

import { InventoryCategoryForm } from "@/components/inventory-categories/InventoryCategoryForm";
import { Breadcrumbs } from "@/components/Breadcrumbs";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { LoadingSkeleton } from "@/components/LoadingSkeleton";
import { PageHeader } from "@/components/PageHeader";
import { StandaloneShell } from "@/components/StandaloneShell";
import { StatusBadge, type StatusTone } from "@/components/StatusBadge";
import { Button } from "@/components/ui/Button";
import type { InventoryCategoryCreate, InventoryCategoryRead } from "@/lib/api/client";
import { AppError } from "@/lib/errors/adapter";
import {
  useCreateInventoryCategory,
  useDeactivateInventoryCategory,
  useInventoryCategories,
  useReactivateInventoryCategory,
  useUpdateInventoryCategory,
} from "@/lib/query/hooks";

function errorMessage(error: unknown): string {
  return error instanceof AppError ? error.message : "Something went wrong. Please try again.";
}

const inputClass =
  "min-h-9 rounded-md border border-border-subtle bg-surface px-2 text-sm text-ink focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-600";

/** Inline rename -- the only mutable field besides status; code is never
 * editable anywhere (docs/domain/STORE_INVENTORY_MODEL.md §5). */
function RenameRow({
  category,
  onCancel,
  onSave,
  isSaving,
}: {
  category: InventoryCategoryRead;
  onCancel: () => void;
  onSave: (name: string) => void;
  isSaving: boolean;
}) {
  const [name, setName] = useState(category.name);
  return (
    <div className="flex items-center gap-2">
      <input
        className={inputClass}
        value={name}
        onChange={(e) => setName(e.target.value)}
        aria-label={`Rename ${category.code}`}
      />
      <Button variant="primary" disabled={isSaving || !name.trim()} onClick={() => onSave(name.trim())}>
        Save
      </Button>
      <Button variant="secondary" disabled={isSaving} onClick={onCancel}>
        Cancel
      </Button>
    </div>
  );
}

export default function InventoryCategoriesPage() {
  const [creating, setCreating] = useState(false);
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [serverError, setServerError] = useState<string | null>(null);
  const [listActionError, setListActionError] = useState<string | null>(null);

  const categoriesQuery = useInventoryCategories();
  const createMutation = useCreateInventoryCategory();
  const updateMutation = useUpdateInventoryCategory();
  const deactivateMutation = useDeactivateInventoryCategory();
  const reactivateMutation = useReactivateInventoryCategory();

  const categories = categoriesQuery.data ?? [];

  function handleSubmit(payload: InventoryCategoryCreate) {
    setServerError(null);
    createMutation.mutate(payload, {
      onSuccess: () => setCreating(false),
      onError: (error) => setServerError(errorMessage(error)),
    });
  }

  return (
    <StandaloneShell>
      <PageHeader
        title="Inventory Categories"
        breadcrumbs={<Breadcrumbs items={[{ label: "Home", href: "/farms" }, { label: "Inventory Categories" }]} />}
        actions={
          !creating && (
            <Button variant="primary" onClick={() => setCreating(true)}>
              <PlusCircle aria-hidden="true" className="h-4 w-4" />
              New category
            </Button>
          )
        }
      />
      <p className="-mt-3 mb-6 text-xs text-ink-muted">
        Tenant-wide classification/reporting metadata for Inventory Items -- never a rule that drives system
        behavior.
      </p>

      {creating && (
        <InventoryCategoryForm
          isSubmitting={createMutation.isPending}
          serverError={serverError}
          onCancel={() => {
            setCreating(false);
            setServerError(null);
          }}
          onSubmit={handleSubmit}
        />
      )}

      {!creating && (
        <>
          {categoriesQuery.isLoading && <LoadingSkeleton rows={4} label="Loading inventory categories" />}
          {categoriesQuery.error && <ErrorState error={categoriesQuery.error} onRetry={() => categoriesQuery.refetch()} />}
          {listActionError && (
            <p role="alert" className="mb-4 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
              {listActionError}
            </p>
          )}
          {!categoriesQuery.isLoading && !categoriesQuery.error && categories.length === 0 && (
            <EmptyState
              title="No inventory categories yet"
              description="Create a classification category before configuring Inventory Items."
            />
          )}
          {!categoriesQuery.isLoading && !categoriesQuery.error && categories.length > 0 && (
            <div className="overflow-x-auto rounded-xl border border-border-subtle bg-surface">
              <table className="w-full text-left text-sm">
                <thead className="border-b border-border-subtle bg-surface-subtle text-xs uppercase text-ink-muted">
                  <tr>
                    <th className="px-4 py-2 font-medium">Code</th>
                    <th className="px-4 py-2 font-medium">Name</th>
                    <th className="px-4 py-2 font-medium">Status</th>
                    <th className="px-4 py-2 font-medium" />
                  </tr>
                </thead>
                <tbody className="divide-y divide-border-subtle">
                  {categories.map((category) => {
                    const tone: StatusTone = category.status === "active" ? "active" : "closed";
                    const isBusy =
                      updateMutation.isPending || deactivateMutation.isPending || reactivateMutation.isPending;
                    return (
                      <tr key={category.id} className="hover:bg-surface-subtle">
                        <td className="px-4 py-2 font-medium text-ink">{category.code}</td>
                        <td className="px-4 py-2 text-ink">
                          {renamingId === category.id ? (
                            <RenameRow
                              category={category}
                              isSaving={updateMutation.isPending}
                              onCancel={() => setRenamingId(null)}
                              onSave={(name) => {
                                setListActionError(null);
                                updateMutation.mutate(
                                  {
                                    categoryId: category.id,
                                    payload: { client_command_id: crypto.randomUUID(), name },
                                  },
                                  {
                                    onSuccess: () => setRenamingId(null),
                                    onError: (error) => setListActionError(errorMessage(error)),
                                  },
                                );
                              }}
                            />
                          ) : (
                            category.name
                          )}
                        </td>
                        <td className="px-4 py-2">
                          <StatusBadge label={category.status === "active" ? "Active" : "Inactive"} tone={tone} />
                        </td>
                        <td className="px-4 py-2">
                          {renamingId !== category.id && (
                            <div className="flex gap-2">
                              <Button variant="secondary" disabled={isBusy} onClick={() => setRenamingId(category.id)}>
                                Rename
                              </Button>
                              {category.status === "active" ? (
                                <Button
                                  variant="secondary"
                                  disabled={isBusy}
                                  onClick={() => {
                                    setListActionError(null);
                                    deactivateMutation.mutate(
                                      { categoryId: category.id, payload: { client_command_id: crypto.randomUUID() } },
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
                                      { categoryId: category.id, payload: { client_command_id: crypto.randomUUID() } },
                                      { onError: (error) => setListActionError(errorMessage(error)) },
                                    );
                                  }}
                                >
                                  Reactivate
                                </Button>
                              )}
                            </div>
                          )}
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
