"use client";

import { ArrowLeft, PlusCircle } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { Breadcrumbs } from "@/components/Breadcrumbs";
import { CarrierSpecificationForm } from "@/components/carrier-specifications/CarrierSpecificationForm";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { LoadingSkeleton } from "@/components/LoadingSkeleton";
import { PageHeader } from "@/components/PageHeader";
import { StatusBadge, type StatusTone } from "@/components/StatusBadge";
import { Button } from "@/components/ui/Button";
import type { CarrierSpecificationCreate, CarrierSpecificationRead, CarrierSpecificationUpdate } from "@/lib/api/client";
import { AppError } from "@/lib/errors/adapter";
import {
  useCarrierSpecifications,
  useCarrierTypes,
  useCreateCarrierSpecification,
  useDeactivateCarrierSpecification,
  useReactivateCarrierSpecification,
  useUpdateCarrierSpecification,
} from "@/lib/query/hooks";

function errorMessage(error: unknown): string {
  return error instanceof AppError ? error.message : "Something went wrong. Please try again.";
}

/** CARRIER-CONFIG-001: a tenant-level configuration page -- deliberately
 * NOT under /farms/[farmId], since a CarrierSpecification is a reusable
 * physical design shared across every farm this tenant has (section 4/28).
 * Manages CarrierSpecification only: Carrier Type is fixed platform
 * metadata (read-only reference here), and individual Carrier registration
 * stays on its own existing flow -- this page is scoped to the reusable
 * design layer in between.
 *
 * UI-OPT-001 Batch B: this route sits outside the /farms/[farmId] layout
 * tree, so it cannot mount AppShell without either inventing a farmId
 * (there isn't one -- this resource has no farm relationship) or picking
 * an arbitrary "last visited farm" to satisfy AppShell's props, which
 * would misrepresent this as farm-scoped. Neither is acceptable, so this
 * page stays a standalone route: same design tokens/typography/shared
 * components as every AppShell-wrapped screen, its own compact brand
 * header (matching AppShell's), and an honest way back into farm context
 * via the existing farm-picker route (/farms) -- never a guessed farm. */
export default function CarrierSpecificationsPage() {
  const [editing, setEditing] = useState<CarrierSpecificationRead | "new" | null>(null);
  const [serverError, setServerError] = useState<string | null>(null);
  const [listActionError, setListActionError] = useState<string | null>(null);

  const typesQuery = useCarrierTypes();
  const specsQuery = useCarrierSpecifications();
  const createMutation = useCreateCarrierSpecification();
  const updateMutation = useUpdateCarrierSpecification();
  const deactivateMutation = useDeactivateCarrierSpecification();
  const reactivateMutation = useReactivateCarrierSpecification();

  const carrierTypes = typesQuery.data ?? [];
  const specifications = specsQuery.data ?? [];

  function closeForm() {
    setEditing(null);
    setServerError(null);
  }

  function handleSubmit(payload: CarrierSpecificationCreate | CarrierSpecificationUpdate) {
    setServerError(null);
    if (editing === "new" || editing === null) {
      createMutation.mutate(payload as CarrierSpecificationCreate, {
        onSuccess: closeForm,
        onError: (error) => setServerError(errorMessage(error)),
      });
    } else {
      updateMutation.mutate(
        { specificationId: editing.id, payload: payload as CarrierSpecificationUpdate },
        {
          onSuccess: closeForm,
          onError: (error) => setServerError(errorMessage(error)),
        },
      );
    }
  }

  const isSubmitting = createMutation.isPending || updateMutation.isPending;
  const isLoading = typesQuery.isLoading || specsQuery.isLoading;
  const loadError = typesQuery.error ?? specsQuery.error;

  return (
    <div className="min-h-screen">
      {/* Standalone brand header, deliberately not AppShell -- see the file
          doc comment above for why. Same brand block/tokens as AppShell's
          own, so the destination still reads as part of CMP. */}
      <div className="border-b border-border-subtle bg-surface px-4 py-3 md:px-6">
        <div className="mx-auto flex max-w-5xl items-center justify-between gap-3">
          <div>
            <div className="font-serif text-base font-semibold leading-tight text-brand-900">ImperialFarms CMP</div>
            <div className="mt-0.5 text-[10px] font-semibold uppercase tracking-wide text-ink-muted">
              Crop Management Platform
            </div>
          </div>
          <Link
            href="/farms"
            className="flex min-h-11 items-center gap-1.5 rounded-md px-3 text-sm font-medium text-ink-muted hover:bg-surface-subtle hover:text-ink focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-600"
          >
            <ArrowLeft aria-hidden="true" className="h-4 w-4" />
            Back to Farms
          </Link>
        </div>
      </div>

      <div className="mx-auto max-w-5xl px-4 py-6 md:px-6">
        <PageHeader
          title="Carrier Specifications"
          breadcrumbs={<Breadcrumbs items={[{ label: "Home", href: "/farms" }, { label: "Carrier Specifications" }]} />}
          actions={
            editing === null && (
              <Button variant="primary" onClick={() => setEditing("new")}>
                <PlusCircle aria-hidden="true" className="h-4 w-4" />
                New specification
              </Button>
            )
          }
        />
        <p className="-mt-3 mb-6 text-xs text-ink-muted">
          Reusable carrier designs shared across every farm in this tenant -- not tied to a single farm.
        </p>

        {editing !== null && !isLoading && !loadError && (
          <CarrierSpecificationForm
            carrierTypes={carrierTypes}
            existing={editing === "new" ? undefined : editing}
            isSubmitting={isSubmitting}
            serverError={serverError}
            onCancel={closeForm}
            onSubmit={handleSubmit}
          />
        )}

        {editing === null && (
          <>
            {isLoading && <LoadingSkeleton rows={4} label="Loading carrier specifications" />}
            {loadError && <ErrorState error={loadError} onRetry={() => { typesQuery.refetch(); specsQuery.refetch(); }} />}
            {listActionError && (
              <p role="alert" className="mb-4 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
                {listActionError}
              </p>
            )}
            {!isLoading && !loadError && specifications.length === 0 && (
              <EmptyState
                title="No carrier specifications yet"
                description="Create a reusable physical design for a carrier type before registering individual carriers against it."
              />
            )}
            {!isLoading && !loadError && specifications.length > 0 && (
              <div className="overflow-x-auto rounded-xl border border-border-subtle bg-surface">
                <table className="w-full text-left text-sm">
                  <thead className="border-b border-border-subtle bg-surface-subtle text-xs uppercase text-ink-muted">
                    <tr>
                      <th className="px-4 py-2 font-medium">Code</th>
                      <th className="px-4 py-2 font-medium">Name</th>
                      <th className="px-4 py-2 font-medium">Carrier Type</th>
                      <th className="px-4 py-2 font-medium">Dimensions (mm)</th>
                      <th className="px-4 py-2 font-medium">Positions</th>
                      <th className="px-4 py-2 font-medium">Status</th>
                      <th className="px-4 py-2 font-medium" />
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border-subtle">
                    {specifications.map((spec) => {
                      const tone: StatusTone = spec.status === "active" ? "active" : "closed";
                      const dims = [spec.length_mm, spec.width_mm, spec.height_mm].every((v) => v === null)
                        ? "—"
                        : [spec.length_mm, spec.width_mm, spec.height_mm].map((v) => v ?? "–").join(" × ");
                      return (
                        <tr key={spec.id} className="hover:bg-surface-subtle">
                          <td className="px-4 py-2 font-medium text-ink">{spec.code}</td>
                          <td className="px-4 py-2 text-ink">{spec.name}</td>
                          <td className="px-4 py-2 text-ink-muted">{spec.carrier_type_code}</td>
                          <td className="px-4 py-2 text-ink-muted">{dims}</td>
                          <td className="px-4 py-2 text-ink-muted">
                            {spec.biological_position_count === null
                              ? "—"
                              : `${spec.biological_position_count} ${(spec.biological_position_label ?? "positions").toLowerCase()}`}
                          </td>
                          <td className="px-4 py-2">
                            <StatusBadge label={spec.status === "active" ? "Active" : "Inactive"} tone={tone} />
                          </td>
                          <td className="px-4 py-2">
                            <div className="flex gap-2">
                              <Button variant="secondary" onClick={() => setEditing(spec)}>
                                Edit
                              </Button>
                              {/* Reversible status toggle only -- never a
                                  delete/remove action; deactivate/reactivate
                                  are the sole lifecycle transitions here. */}
                              {spec.status === "active" ? (
                                <Button
                                  variant="secondary"
                                  onClick={() => {
                                    setListActionError(null);
                                    deactivateMutation.mutate(spec.id, {
                                      onError: (error) => setListActionError(errorMessage(error)),
                                    });
                                  }}
                                  disabled={deactivateMutation.isPending}
                                >
                                  Deactivate
                                </Button>
                              ) : (
                                <Button
                                  variant="secondary"
                                  onClick={() => {
                                    setListActionError(null);
                                    reactivateMutation.mutate(spec.id, {
                                      onError: (error) => setListActionError(errorMessage(error)),
                                    });
                                  }}
                                  disabled={reactivateMutation.isPending}
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
      </div>
    </div>
  );
}
