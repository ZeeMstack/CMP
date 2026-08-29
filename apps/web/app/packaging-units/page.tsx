"use client";

import { PlusCircle } from "lucide-react";
import { useState } from "react";

import { Breadcrumbs } from "@/components/Breadcrumbs";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { LoadingSkeleton } from "@/components/LoadingSkeleton";
import { PackagingUnitForm } from "@/components/packaging-units/PackagingUnitForm";
import { PageHeader } from "@/components/PageHeader";
import { StandaloneShell } from "@/components/StandaloneShell";
import { StatusBadge, type StatusTone } from "@/components/StatusBadge";
import { Button } from "@/components/ui/Button";
import type { PackagingUnitCreate } from "@/lib/api/client";
import { AppError } from "@/lib/errors/adapter";
import { useCreatePackagingUnit, usePackagingUnits, useRetirePackagingUnit } from "@/lib/query/hooks";

function errorMessage(error: unknown): string {
  return error instanceof AppError ? error.message : "Something went wrong. Please try again.";
}

/** PILOT-SETUP-001B7: tenant-scoped, unversioned master data -- no
 * `farm_id` on `PackagingUnit`, so this stays a standalone route outside
 * `/farms/[farmId]`, mirroring Carrier Specifications' own single-page
 * list+create+retire pattern exactly (`app/carrier-specifications/page.tsx`).
 * No edit endpoint exists for Packaging Unit -- code/name are frozen once
 * created; retirement is the only lifecycle transition, and it is
 * irreversible (no reactivate endpoint), so it is never offered lightly. */
export default function PackagingUnitsPage() {
  const [creating, setCreating] = useState(false);
  const [serverError, setServerError] = useState<string | null>(null);
  const [listActionError, setListActionError] = useState<string | null>(null);

  const unitsQuery = usePackagingUnits();
  const createMutation = useCreatePackagingUnit();
  const retireMutation = useRetirePackagingUnit();

  const units = unitsQuery.data ?? [];

  function handleSubmit(payload: PackagingUnitCreate) {
    setServerError(null);
    createMutation.mutate(payload, {
      onSuccess: () => setCreating(false),
      onError: (error) => setServerError(errorMessage(error)),
    });
  }

  return (
    <StandaloneShell>
      <PageHeader
        title="Packaging Units"
        breadcrumbs={<Breadcrumbs items={[{ label: "Home", href: "/farms" }, { label: "Packaging Units" }]} />}
        actions={
          !creating && (
            <Button variant="primary" onClick={() => setCreating(true)}>
              <PlusCircle aria-hidden="true" className="h-4 w-4" />
              New packaging unit
            </Button>
          )
        }
      />
      <p className="-mt-3 mb-6 text-xs text-ink-muted">
        Tenant-wide reusable packaging identities (e.g. carton, clamshell, crate). Pack size (weight or unit count)
        is configured per Pack Specification Version, not here.
      </p>

      {creating && (
        <PackagingUnitForm
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
          {unitsQuery.isLoading && <LoadingSkeleton rows={4} label="Loading packaging units" />}
          {unitsQuery.error && <ErrorState error={unitsQuery.error} onRetry={() => unitsQuery.refetch()} />}
          {listActionError && (
            <p role="alert" className="mb-4 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
              {listActionError}
            </p>
          )}
          {!unitsQuery.isLoading && !unitsQuery.error && units.length === 0 && (
            <EmptyState
              title="No packaging units yet"
              description="Create a reusable packaging identity before configuring a Pack Specification Version against it."
            />
          )}
          {!unitsQuery.isLoading && !unitsQuery.error && units.length > 0 && (
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
                  {units.map((unit) => {
                    const tone: StatusTone = unit.status === "active" ? "active" : "closed";
                    return (
                      <tr key={unit.id} className="hover:bg-surface-subtle">
                        <td className="px-4 py-2 font-medium text-ink">{unit.code}</td>
                        <td className="px-4 py-2 text-ink">{unit.name}</td>
                        <td className="px-4 py-2">
                          <StatusBadge label={unit.status === "active" ? "Active" : "Retired"} tone={tone} />
                        </td>
                        <td className="px-4 py-2">
                          {unit.status === "active" && (
                            <Button
                              variant="secondary"
                              disabled={retireMutation.isPending}
                              onClick={() => {
                                setListActionError(null);
                                retireMutation.mutate(
                                  { packagingUnitId: unit.id, payload: { client_command_id: crypto.randomUUID() } },
                                  { onError: (error) => setListActionError(errorMessage(error)) },
                                );
                              }}
                            >
                              Retire
                            </Button>
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
