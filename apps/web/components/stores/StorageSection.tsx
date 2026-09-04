"use client";

import { PlusCircle } from "lucide-react";
import { useState } from "react";

import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { LoadingSkeleton } from "@/components/LoadingSkeleton";
import { StoreCreateForm } from "@/components/stores/StoreCreateForm";
import { StoreTreeView, type StoreRowError } from "@/components/stores/StoreTreeView";
import { Button } from "@/components/ui/Button";
import type { LocationBulkChildrenCreate, LocationCreate, LocationTreeNode } from "@/lib/api/client";
import { AppError } from "@/lib/errors/adapter";
import {
  activeOnly,
  extractStoreRoots,
  flattenStoreTree,
  STORE_TYPE_LABELS,
  type StoreTypeCode,
} from "@/lib/format/storeTree";
import {
  useBulkCreateLocationChildren,
  useCreateLocation,
  useDeactivateLocation,
  useLocationsTree,
  useReactivateLocation,
  useUpdateLocation,
} from "@/lib/query/hooks";

function errorMessage(error: unknown): string {
  return error instanceof AppError ? error.message : "Something went wrong. Please try again.";
}

function errorCode(error: unknown): string | null {
  return error instanceof AppError ? error.code : null;
}

function typeLabel(node: LocationTreeNode | null): string {
  if (!node) return "location";
  const code = node.location_type_code as StoreTypeCode;
  return STORE_TYPE_LABELS[code] ?? "location";
}

/** Depth-first search returning both the target node and its immediate
 * parent (null for a root Store) -- used to build friendly blocked-action
 * copy from data the page already has, with no extra request. */
function findNodeWithParent(
  nodes: LocationTreeNode[],
  id: string,
  parent: LocationTreeNode | null = null,
): [LocationTreeNode, LocationTreeNode | null] | [null, null] {
  for (const node of nodes) {
    if (node.id === id) return [node, parent];
    const found = findNodeWithParent(node.children as LocationTreeNode[], id, node);
    if (found[0]) return found;
  }
  return [null, null];
}

/** docs/domain/STORE_INVENTORY_MODEL.md §19 / LOCATION_MODEL.md "Location
 * maintenance lifecycle": map the backend's stable `code` (never raw
 * exception text) to operator language, using the already-loaded tree data
 * to name the actual blocking children/parent rather than a generic count. */
function friendlyDeactivateMessage(node: LocationTreeNode | null, code: string | null, fallback: string): string {
  if (code === "LOCATION_HAS_ACTIVE_CHILDREN" && node) {
    const activeChildren = (node.children as LocationTreeNode[]).filter((c) => c.status === "active");
    const firstType = activeChildren[0]?.location_type_code as StoreTypeCode | undefined;
    const sameType = firstType && activeChildren.every((c) => c.location_type_code === firstType);
    const childLabel = sameType
      ? `${STORE_TYPE_LABELS[firstType] ?? "location"}${activeChildren.length === 1 ? "" : "s"}`
      : "location(s)";
    const verb = activeChildren.length === 1 ? "remains" : "remain";
    return `Cannot deactivate this ${typeLabel(node)} because ${activeChildren.length} active ${childLabel} ${verb} beneath it.`;
  }
  if (code === "LOCATION_HAS_ACTIVE_OCCUPANCY") {
    return `Cannot deactivate this ${typeLabel(node)} because it currently has an active occupancy.`;
  }
  return fallback;
}

function friendlyReactivateMessage(
  node: LocationTreeNode | null,
  parent: LocationTreeNode | null,
  code: string | null,
  fallback: string,
): string {
  if (code === "LOCATION_PARENT_NOT_ACTIVE") {
    return `Cannot reactivate this ${typeLabel(node)} until its parent ${typeLabel(parent)} is active.`;
  }
  return fallback;
}

/** UX-IA-001: the Storage view within the Store & Inventory Setup
 * workspace -- extracted, unchanged in substance, from the pre-existing
 * `/farms/[farmId]/stores` page (docs/domain/STORE_INVENTORY_MODEL.md §4/
 * §9: a purpose-built, Store-rooted view over the generic Location tree/
 * create/bulk-generation infrastructure, never merged with Greenhouse
 * setup). Rendered by both that legacy route and the new workspace
 * `storage` child route -- one implementation, two thin wrappers. */
export function StorageSection({ farmId }: { farmId: string }) {
  const { data, isLoading, error, refetch } = useLocationsTree(farmId);
  const [showAddForm, setShowAddForm] = useState(false);
  const [serverError, setServerError] = useState<string | null>(null);
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [rowError, setRowError] = useState<StoreRowError | null>(null);

  const createLocation = useCreateLocation(farmId);
  const bulkCreateChildren = useBulkCreateLocationChildren(farmId);
  const updateLocation = useUpdateLocation(farmId);
  const deactivateLocation = useDeactivateLocation(farmId);
  const reactivateLocation = useReactivateLocation(farmId);
  const isSubmitting = createLocation.isPending || bulkCreateChildren.isPending;
  const isMutatingRow = updateLocation.isPending || deactivateLocation.isPending || reactivateLocation.isPending;

  const storeRoots = extractStoreRoots(data ?? []);
  const flattened = flattenStoreTree(storeRoots);
  // UX-IA-001: only active parents are offered -- the backend remains
  // independently authoritative (InactiveParentLocationError).
  const storeOnlyOptions = activeOnly(flattened.filter((o) => o.typeCode === "store"));
  const areaAndStoreOptions = activeOnly(flattened.filter((o) => o.typeCode === "store" || o.typeCode === "store_area"));
  const anyParentOptions = activeOnly(flattened.filter((o) => o.typeCode !== "store_bin"));

  function closeForm() {
    setShowAddForm(false);
    setServerError(null);
  }

  function submitSingle(payload: LocationCreate) {
    setServerError(null);
    createLocation.mutate(payload, {
      onSuccess: closeForm,
      onError: (err) => setServerError(errorMessage(err)),
    });
  }

  function submitBulk(parentId: string, payload: LocationBulkChildrenCreate) {
    setServerError(null);
    bulkCreateChildren.mutate(
      { parentId, payload },
      { onSuccess: closeForm, onError: (err) => setServerError(errorMessage(err)) },
    );
  }

  function handleStartRename(locationId: string) {
    setRowError(null);
    setRenamingId(locationId);
  }

  function handleRename(locationId: string, name: string) {
    setRowError(null);
    updateLocation.mutate(
      { locationId, payload: { client_command_id: crypto.randomUUID(), name } },
      {
        onSuccess: () => setRenamingId(null),
        onError: (err) => setRowError({ locationId, message: errorMessage(err) }),
      },
    );
  }

  function handleDeactivate(locationId: string) {
    setRowError(null);
    const [node] = findNodeWithParent(storeRoots, locationId);
    deactivateLocation.mutate(
      { locationId, payload: { client_command_id: crypto.randomUUID() } },
      {
        onError: (err) =>
          setRowError({ locationId, message: friendlyDeactivateMessage(node, errorCode(err), errorMessage(err)) }),
      },
    );
  }

  function handleReactivate(locationId: string) {
    setRowError(null);
    const [node, parent] = findNodeWithParent(storeRoots, locationId);
    reactivateLocation.mutate(
      { locationId, payload: { client_command_id: crypto.randomUUID() } },
      {
        onError: (err) =>
          setRowError({
            locationId,
            message: friendlyReactivateMessage(node, parent, errorCode(err), errorMessage(err)),
          }),
      },
    );
  }

  return (
    <div>
      {!showAddForm && (
        <div className="mb-4 flex justify-end">
          <Button variant="primary" onClick={() => setShowAddForm(true)}>
            <PlusCircle aria-hidden="true" className="h-4 w-4" />
            Add
          </Button>
        </div>
      )}
      <p className="mb-6 text-xs text-ink-muted">
        A Farm may have multiple Stores. Area and Rack are optional -- a Bin may attach directly to a Store, to an
        Area, to a Rack, or to an Area&apos;s Rack.
      </p>

      {showAddForm && (
        <StoreCreateForm
          storeRoots={storeOnlyOptions}
          areaAndStoreOptions={areaAndStoreOptions}
          anyParentOptions={anyParentOptions}
          isSubmitting={isSubmitting}
          serverError={serverError}
          onCancel={closeForm}
          onSubmitStore={submitSingle}
          onSubmitArea={submitSingle}
          onSubmitRack={submitSingle}
          onSubmitBinSingle={submitSingle}
          onSubmitBinBulk={submitBulk}
        />
      )}

      {!showAddForm && (
        <>
          {isLoading && <LoadingSkeleton rows={6} label="Loading stores" />}
          {error && <ErrorState error={error} onRetry={() => refetch()} />}
          {!isLoading && !error && storeRoots.length === 0 && (
            <EmptyState title="No Stores yet" description="Create the first Store for this Farm." />
          )}
          {!isLoading && !error && storeRoots.length > 0 && (
            <StoreTreeView
              storeRoots={storeRoots}
              renamingId={renamingId}
              isMutating={isMutatingRow}
              rowError={rowError}
              onStartRename={handleStartRename}
              onCancelRename={() => setRenamingId(null)}
              onRename={handleRename}
              onDeactivate={handleDeactivate}
              onReactivate={handleReactivate}
            />
          )}
        </>
      )}
    </div>
  );
}
