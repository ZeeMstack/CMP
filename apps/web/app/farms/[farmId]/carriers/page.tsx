"use client";

import { PlusCircle, Settings } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useMemo, useState } from "react";

import { Breadcrumbs } from "@/components/Breadcrumbs";
import { CarrierRegistrationForm } from "@/components/carriers/CarrierRegistrationForm";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { LoadingSkeleton } from "@/components/LoadingSkeleton";
import { PageHeader } from "@/components/PageHeader";
import { StatusBadge, type StatusTone } from "@/components/StatusBadge";
import { Button } from "@/components/ui/Button";
import { AppError } from "@/lib/errors/adapter";
import { isSelectableForCarrierRegistration } from "@/lib/validation/carrierRegistration";
import {
  useBulkRegisterCarriers,
  useCarriers,
  useCarrierSpecifications,
  useCarrierTypes,
  useRegisterCarrier,
} from "@/lib/query/hooks";

function errorMessage(error: unknown): string {
  return error instanceof AppError ? error.message : "Something went wrong. Please try again.";
}

/** PILOT-SETUP-001B5: farm-scoped, unlike Carrier Specifications
 * (/carrier-specifications, tenant-level) -- the physical Carrier itself
 * has a required `farm_id`, so this page lives under /farms/[farmId] and
 * inherits AppShell/farm context from that layout automatically. This
 * page registers the reusable physical object only: no Location, Crop
 * Batch, plant count, or Occupancy/Movement/Transformation field or call
 * exists anywhere here -- a registered Carrier is created unoccupied. */
export default function CarriersPage() {
  const { farmId } = useParams<{ farmId: string }>();
  const [showRegisterForm, setShowRegisterForm] = useState(false);
  const [serverError, setServerError] = useState<string | null>(null);

  const carriersQuery = useCarriers(farmId);
  const specsQuery = useCarrierSpecifications();
  const typesQuery = useCarrierTypes();
  const registerMutation = useRegisterCarrier(farmId);
  const bulkRegisterMutation = useBulkRegisterCarriers(farmId);

  const carriers = carriersQuery.data ?? [];
  // FINAL INTEGRITY CLEANUP: excludes both inactive specs AND the legacy
  // generic `cultivation_plate` type from new registration -- the list
  // below (historical Carriers already registered, including any legacy
  // ones) is never filtered by this, only the registration picker is.
  const registrableSpecifications = useMemo(
    () => (specsQuery.data ?? []).filter(isSelectableForCarrierRegistration),
    [specsQuery.data],
  );
  const typeNameById = useMemo(
    () => new Map((typesQuery.data ?? []).map((t) => [t.id, t.name])),
    [typesQuery.data],
  );

  const isSubmitting = registerMutation.isPending || bulkRegisterMutation.isPending;
  const isLoading = carriersQuery.isLoading || specsQuery.isLoading || typesQuery.isLoading;
  const loadError = carriersQuery.error ?? specsQuery.error ?? typesQuery.error;

  function closeForm() {
    setShowRegisterForm(false);
    setServerError(null);
  }

  return (
    <div>
      <PageHeader
        title="Physical Carriers"
        breadcrumbs={
          <Breadcrumbs items={[{ label: "Home", href: `/farms/${farmId}` }, { label: "Physical Carriers" }]} />
        }
        actions={
          !showRegisterForm && (
            <div className="flex flex-wrap items-center gap-2">
              <Link
                href="/carrier-specifications"
                className="flex min-h-11 items-center gap-1.5 rounded-md border border-border-subtle bg-surface px-3 text-sm font-medium text-ink hover:bg-surface-subtle focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-600"
              >
                <Settings aria-hidden="true" className="h-4 w-4" />
                Manage Carrier Specifications
              </Link>
              <Button variant="primary" onClick={() => setShowRegisterForm(true)}>
                <PlusCircle aria-hidden="true" className="h-4 w-4" />
                Register carriers
              </Button>
            </div>
          )
        }
      />
      <p className="-mt-3 mb-6 text-xs text-ink-muted">
        Reusable physical carriers registered to this farm. Registering a carrier does not place it anywhere --
        placement happens in the operational workflow that first uses it.
      </p>

      {showRegisterForm && !isLoading && !loadError && (
        <CarrierRegistrationForm
          specifications={registrableSpecifications}
          isSubmitting={isSubmitting}
          serverError={serverError}
          onCancel={closeForm}
          onSubmitSingle={(payload) => {
            setServerError(null);
            registerMutation.mutate(payload, {
              onSuccess: closeForm,
              onError: (error) => setServerError(errorMessage(error)),
            });
          }}
          onSubmitBulk={(payload) => {
            setServerError(null);
            bulkRegisterMutation.mutate(payload, {
              onSuccess: closeForm,
              onError: (error) => setServerError(errorMessage(error)),
            });
          }}
        />
      )}

      {!showRegisterForm && (
        <>
          {isLoading && <LoadingSkeleton rows={4} label="Loading carriers" />}
          {loadError && (
            <ErrorState
              error={loadError}
              onRetry={() => {
                carriersQuery.refetch();
                specsQuery.refetch();
                typesQuery.refetch();
              }}
            />
          )}
          {!isLoading && !loadError && carriers.length === 0 && (
            <EmptyState
              title="No physical carriers registered yet"
              description="Register a carrier against an existing, active carrier specification."
            />
          )}
          {!isLoading && !loadError && carriers.length > 0 && (
            <div className="overflow-x-auto rounded-xl border border-border-subtle bg-surface">
              <table className="w-full text-left text-sm">
                <thead className="border-b border-border-subtle bg-surface-subtle text-xs uppercase text-ink-muted">
                  <tr>
                    <th className="px-4 py-2 font-medium">Code</th>
                    <th className="px-4 py-2 font-medium">Carrier Type</th>
                    <th className="px-4 py-2 font-medium">Specification</th>
                    <th className="px-4 py-2 font-medium">Status</th>
                    <th className="px-4 py-2 font-medium">Issued</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border-subtle">
                  {carriers.map((carrier) => {
                    const tone: StatusTone = carrier.status === "active" ? "active" : "closed";
                    return (
                      <tr key={carrier.id} className="hover:bg-surface-subtle">
                        <td className="px-4 py-2 font-medium text-ink">{carrier.code}</td>
                        <td className="px-4 py-2 text-ink-muted">
                          {typeNameById.get(carrier.carrier_type_id) ?? "—"}
                        </td>
                        <td className="px-4 py-2 text-ink-muted">
                          {carrier.specification ? `${carrier.specification.code} — ${carrier.specification.name}` : "—"}
                        </td>
                        <td className="px-4 py-2">
                          <StatusBadge label={carrier.status} tone={tone} />
                        </td>
                        <td className="px-4 py-2 text-ink-muted">{carrier.issued_date ?? "—"}</td>
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
  );
}
