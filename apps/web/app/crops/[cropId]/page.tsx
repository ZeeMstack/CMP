"use client";

import { PlusCircle } from "lucide-react";
import { useParams } from "next/navigation";
import { useState } from "react";

import { Breadcrumbs } from "@/components/Breadcrumbs";
import { VarietyForm } from "@/components/crops/VarietyForm";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { LoadingSkeleton } from "@/components/LoadingSkeleton";
import { PageHeader } from "@/components/PageHeader";
import { StandaloneShell } from "@/components/StandaloneShell";
import { StatusBadge, type StatusTone } from "@/components/StatusBadge";
import { Button } from "@/components/ui/Button";
import type { VarietyCreate } from "@/lib/api/client";
import { AppError } from "@/lib/errors/adapter";
import { useCreateVariety, useCrops, useVarieties } from "@/lib/query/hooks";

function errorMessage(error: unknown): string {
  return error instanceof AppError ? error.message : "Something went wrong. Please try again.";
}

/** PILOT-SETUP-001B6: no `GET /crops/{id}` read is called here -- the
 * backend has one (`get_crop`), but the tenant-wide Crop list this app
 * already fetches for the Crops page (`useCrops`) is cached and cheap
 * enough that a second per-crop request is unnecessary; the Crop shown here
 * is found by id in that same list. Varieties are always created against
 * this page's own Crop -- never a free-typed crop id. */
export default function CropVarietiesPage() {
  const { cropId } = useParams<{ cropId: string }>();
  const [creating, setCreating] = useState(false);
  const [serverError, setServerError] = useState<string | null>(null);

  const cropsQuery = useCrops();
  const varietiesQuery = useVarieties(cropId);
  const createMutation = useCreateVariety(cropId);

  const crop = cropsQuery.data?.find((c) => c.id === cropId);
  const varieties = varietiesQuery.data ?? [];

  function handleSubmit(payload: VarietyCreate) {
    setServerError(null);
    createMutation.mutate(payload, {
      onSuccess: () => setCreating(false),
      onError: (error) => setServerError(errorMessage(error)),
    });
  }

  const isLoading = cropsQuery.isLoading || varietiesQuery.isLoading;
  const loadError = cropsQuery.error ?? varietiesQuery.error;

  return (
    <StandaloneShell>
      <PageHeader
        title={crop ? `${crop.common_name} — Varieties` : "Varieties"}
        breadcrumbs={
          <Breadcrumbs
            items={[
              { label: "Home", href: "/farms" },
              { label: "Crops", href: "/crops" },
              { label: crop?.common_name ?? "Crop" },
            ]}
          />
        }
        actions={
          !creating &&
          crop && (
            <Button variant="primary" onClick={() => setCreating(true)}>
              <PlusCircle aria-hidden="true" className="h-4 w-4" />
              New variety
            </Button>
          )
        }
      />

      {isLoading && <LoadingSkeleton rows={4} label="Loading crop and varieties" />}
      {loadError && (
        <ErrorState
          error={loadError}
          onRetry={() => {
            cropsQuery.refetch();
            varietiesQuery.refetch();
          }}
        />
      )}

      {!isLoading && !loadError && !crop && (
        <ErrorState error={new AppError("not_found", "This crop could not be found.")} />
      )}

      {!isLoading && !loadError && crop && (
        <>
          {creating && (
            <VarietyForm
              isSubmitting={createMutation.isPending}
              serverError={serverError}
              onCancel={() => {
                setCreating(false);
                setServerError(null);
              }}
              onSubmit={handleSubmit}
            />
          )}

          {!creating && varieties.length === 0 && (
            <EmptyState
              title="No varieties yet"
              description="Register at least one variety before configuring a workflow for this crop, or leave the workflow variety-agnostic."
            />
          )}

          {!creating && varieties.length > 0 && (
            <div className="overflow-x-auto rounded-xl border border-border-subtle bg-surface">
              <table className="w-full text-left text-sm">
                <thead className="border-b border-border-subtle bg-surface-subtle text-xs uppercase text-ink-muted">
                  <tr>
                    <th className="px-4 py-2 font-medium">Code</th>
                    <th className="px-4 py-2 font-medium">Name</th>
                    <th className="px-4 py-2 font-medium">Supplier reference</th>
                    <th className="px-4 py-2 font-medium">Status</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border-subtle">
                  {varieties.map((variety) => {
                    const tone: StatusTone = variety.status === "active" ? "active" : "closed";
                    return (
                      <tr key={variety.id} className="hover:bg-surface-subtle">
                        <td className="px-4 py-2 font-medium text-ink">{variety.code}</td>
                        <td className="px-4 py-2 text-ink">{variety.name}</td>
                        <td className="px-4 py-2 text-ink-muted">{variety.supplier_reference ?? "—"}</td>
                        <td className="px-4 py-2">
                          <StatusBadge label={variety.status === "active" ? "Active" : "Inactive"} tone={tone} />
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
