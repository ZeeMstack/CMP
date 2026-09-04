"use client";

import { PlusCircle } from "lucide-react";
import { useParams } from "next/navigation";
import { useState } from "react";

import { Breadcrumbs } from "@/components/Breadcrumbs";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { LoadingSkeleton } from "@/components/LoadingSkeleton";
import { PageHeader } from "@/components/PageHeader";
import { StoreCreateForm } from "@/components/stores/StoreCreateForm";
import { StoreTreeView } from "@/components/stores/StoreTreeView";
import { Button } from "@/components/ui/Button";
import type { LocationBulkChildrenCreate, LocationCreate } from "@/lib/api/client";
import { AppError } from "@/lib/errors/adapter";
import { extractStoreRoots, flattenStoreTree } from "@/lib/format/storeTree";
import { useBulkCreateLocationChildren, useCreateLocation, useLocationsTree } from "@/lib/query/hooks";

function errorMessage(error: unknown): string {
  return error instanceof AppError ? error.message : "Something went wrong. Please try again.";
}

/** docs/domain/STORE_INVENTORY_MODEL.md §4/§9: a purpose-built,
 * Store-rooted view over the existing generic Location tree/create/
 * bulk-generation infrastructure -- never merged with Greenhouse setup.
 * The Location backend remains fully authoritative; this page only
 * constrains what the operator is offered. */
export default function StoresAndBinsPage() {
  const { farmId } = useParams<{ farmId: string }>();
  const { data, isLoading, error, refetch } = useLocationsTree(farmId);
  const [showAddForm, setShowAddForm] = useState(false);
  const [serverError, setServerError] = useState<string | null>(null);

  const createLocation = useCreateLocation(farmId);
  const bulkCreateChildren = useBulkCreateLocationChildren(farmId);
  const isSubmitting = createLocation.isPending || bulkCreateChildren.isPending;

  const storeRoots = extractStoreRoots(data ?? []);
  const flattened = flattenStoreTree(storeRoots);
  const storeOnlyOptions = flattened.filter((o) => o.typeCode === "store");
  const areaAndStoreOptions = flattened.filter((o) => o.typeCode === "store" || o.typeCode === "store_area");
  const anyParentOptions = flattened.filter((o) => o.typeCode !== "store_bin");

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

  return (
    <div>
      <PageHeader
        title="Stores & Bins"
        breadcrumbs={<Breadcrumbs items={[{ label: "Home", href: `/farms/${farmId}` }, { label: "Stores & Bins" }]} />}
        actions={
          !showAddForm && (
            <Button variant="primary" onClick={() => setShowAddForm(true)}>
              <PlusCircle aria-hidden="true" className="h-4 w-4" />
              Add
            </Button>
          )
        }
      />
      <p className="-mt-3 mb-6 text-xs text-ink-muted">
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
          {!isLoading && !error && storeRoots.length > 0 && <StoreTreeView storeRoots={storeRoots} />}
        </>
      )}
    </div>
  );
}
