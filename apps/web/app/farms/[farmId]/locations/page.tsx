"use client";

import { Package, PlusCircle, Wrench } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";

import { Breadcrumbs } from "@/components/Breadcrumbs";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { LoadingSkeleton } from "@/components/LoadingSkeleton";
import { LocationCreateForm } from "@/components/locations/LocationCreateForm";
import { LocationTree } from "@/components/LocationTree";
import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/components/ui/Button";
import { AppError } from "@/lib/errors/adapter";
import { flattenLocationTree } from "@/lib/format/locationTree";
import { useBulkCreateLocationChildren, useCreateLocation, useLocationsTree } from "@/lib/query/hooks";

function errorMessage(error: unknown): string {
  return error instanceof AppError ? error.message : "Something went wrong. Please try again.";
}

export default function LocationsPage() {
  const { farmId } = useParams<{ farmId: string }>();
  const { data, isLoading, error, refetch } = useLocationsTree(farmId);
  const [showAddForm, setShowAddForm] = useState(false);
  const [serverError, setServerError] = useState<string | null>(null);

  const createLocation = useCreateLocation(farmId);
  const bulkCreateChildren = useBulkCreateLocationChildren(farmId);
  const isSubmitting = createLocation.isPending || bulkCreateChildren.isPending;

  function closeForm() {
    setShowAddForm(false);
    setServerError(null);
  }

  return (
    <div>
      <PageHeader
        title="Locations"
        breadcrumbs={
          <Breadcrumbs items={[{ label: "Home", href: `/farms/${farmId}` }, { label: "Locations" }]} />
        }
        actions={
          !showAddForm && (
            <div className="flex flex-wrap items-center gap-2">
              <Link
                href={`/farms/${farmId}/carriers`}
                className="flex min-h-11 items-center gap-1.5 rounded-md border border-border-subtle bg-surface px-3 text-sm font-medium text-ink hover:bg-surface-subtle focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-600"
              >
                <Package aria-hidden="true" className="h-4 w-4" />
                Physical Carriers
              </Link>
              <Link
                href={`/farms/${farmId}/farm-setup`}
                className="flex min-h-11 items-center gap-1.5 rounded-md border border-border-subtle bg-surface px-3 text-sm font-medium text-ink hover:bg-surface-subtle focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-600"
              >
                <Wrench aria-hidden="true" className="h-4 w-4" />
                View Farm Setup
              </Link>
              <Button variant="primary" onClick={() => setShowAddForm(true)}>
                <PlusCircle aria-hidden="true" className="h-4 w-4" />
                Add location
              </Button>
            </div>
          )
        }
      />
      {/* This is the operational occupancy view (what's placed where, right
          now) -- distinct from Farm Setup, which defines physical
          structure. Structural edits happen there, not here. Generic
          structural locations Farm Setup doesn't cover (Store, Packing
          Hall, Cold Store and its Positions, Dispatch Area) are created
          right here instead -- see LocationCreateForm's own doc comment. */}
      <p className="-mt-3 mb-6 text-xs text-ink-muted">
        Current occupancy across this farm&apos;s location hierarchy. To change greenhouse structure, use Farm Setup.
      </p>

      {showAddForm && (
        <LocationCreateForm
          parentOptions={flattenLocationTree(data ?? [])}
          isSubmitting={isSubmitting}
          serverError={serverError}
          onCancel={closeForm}
          onSubmitSingle={(payload) => {
            setServerError(null);
            createLocation.mutate(payload, {
              onSuccess: closeForm,
              onError: (err) => setServerError(errorMessage(err)),
            });
          }}
          onSubmitBulk={(parentId, payload) => {
            setServerError(null);
            bulkCreateChildren.mutate(
              { parentId, payload },
              {
                onSuccess: closeForm,
                onError: (err) => setServerError(errorMessage(err)),
              },
            );
          }}
        />
      )}

      {!showAddForm && (
        <>
          {isLoading && <LoadingSkeleton rows={6} label="Loading locations" />}
          {error && <ErrorState error={error} onRetry={() => refetch()} />}
          {data && data.length === 0 && (
            <EmptyState title="No locations yet" description="This farm has no location hierarchy configured." />
          )}
          {data && data.length > 0 && (
            <div className="rounded-xl border border-border-subtle bg-surface p-2">
              <LocationTree nodes={data} farmId={farmId} />
            </div>
          )}
        </>
      )}
    </div>
  );
}
