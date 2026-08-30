"use client";

import { PlusCircle } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Breadcrumbs } from "@/components/Breadcrumbs";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { LoadingSkeleton } from "@/components/LoadingSkeleton";
import { PackSpecificationForm } from "@/components/pack-specifications/PackSpecificationForm";
import { PageHeader } from "@/components/PageHeader";
import { StandaloneShell } from "@/components/StandaloneShell";
import { Button } from "@/components/ui/Button";
import type { CropRead, PackSpecificationCreate, PackSpecificationRead } from "@/lib/api/client";
import { AppError } from "@/lib/errors/adapter";
import { useAllPackSpecifications, useCreatePackSpecification, useCrops, useVarieties } from "@/lib/query/hooks";

function errorMessage(error: unknown): string {
  return error instanceof AppError ? error.message : "Something went wrong. Please try again.";
}

/** PILOT-SETUP-001B7: tenant-scoped commercial pack/product master data (no
 * `farm_id` on `PackSpecification`), so this stays a standalone route
 * outside `/farms/[farmId]`, mirroring `GradeDefinitionsPage` exactly. */
export default function PackSpecificationsPage() {
  const router = useRouter();
  const [creating, setCreating] = useState(false);
  const [serverError, setServerError] = useState<string | null>(null);

  const specsQuery = useAllPackSpecifications();
  const cropsQuery = useCrops();
  const createMutation = useCreatePackSpecification();

  const specs = specsQuery.data ?? [];
  const crops = cropsQuery.data ?? [];

  const isLoading = specsQuery.isLoading || cropsQuery.isLoading;
  const loadError = specsQuery.error ?? cropsQuery.error;

  function handleSubmit(payload: PackSpecificationCreate) {
    setServerError(null);
    createMutation.mutate(payload, {
      onSuccess: (spec) => router.push(`/pack-specifications/${spec.id}`),
      onError: (error) => setServerError(errorMessage(error)),
    });
  }

  return (
    <StandaloneShell>
      <PageHeader
        title="Pack Specifications"
        breadcrumbs={<Breadcrumbs items={[{ label: "Home", href: "/farms" }, { label: "Pack Specifications" }]} />}
        actions={
          !creating && (
            <Button variant="primary" onClick={() => setCreating(true)}>
              <PlusCircle aria-hidden="true" className="h-4 w-4" />
              New pack specification
            </Button>
          )
        }
      />
      <p className="-mt-3 mb-6 text-xs text-ink-muted">
        Tenant-wide commercial pack/product identities. Configuration only -- actual packing of graded produce
        happens on the Packing screen inside a Farm.
      </p>

      {isLoading && <LoadingSkeleton rows={4} label="Loading pack specifications" />}
      {loadError && (
        <ErrorState
          error={loadError}
          onRetry={() => {
            specsQuery.refetch();
            cropsQuery.refetch();
          }}
        />
      )}

      {!isLoading && !loadError && creating && (
        <PackSpecificationForm
          crops={crops}
          isSubmitting={createMutation.isPending}
          serverError={serverError}
          onCancel={() => {
            setCreating(false);
            setServerError(null);
          }}
          onSubmit={handleSubmit}
        />
      )}

      {!isLoading && !loadError && !creating && specs.length === 0 && (
        <EmptyState
          title="No pack specifications yet"
          description="Create the first commercial pack identity, then version it with a packaging unit and pack size."
        />
      )}

      {!isLoading && !loadError && !creating && specs.length > 0 && (
        <PackSpecificationsTable specs={specs} crops={crops} />
      )}
    </StandaloneShell>
  );
}

function PackSpecificationsTable({ specs, crops }: { specs: PackSpecificationRead[]; crops: CropRead[] }) {
  return (
    <div className="overflow-x-auto rounded-xl border border-border-subtle bg-surface">
      <table className="w-full text-left text-sm">
        <thead className="border-b border-border-subtle bg-surface-subtle text-xs uppercase text-ink-muted">
          <tr>
            <th className="px-4 py-2 font-medium">Code</th>
            <th className="px-4 py-2 font-medium">Name</th>
            <th className="px-4 py-2 font-medium">Crop</th>
            <th className="px-4 py-2 font-medium">Variety</th>
            <th className="px-4 py-2 font-medium">Customer reference</th>
            <th className="px-4 py-2 font-medium" />
          </tr>
        </thead>
        <tbody className="divide-y divide-border-subtle">
          {specs.map((spec) => {
            const crop = crops.find((c) => c.id === spec.crop_id);
            return (
              <PackSpecificationRow key={spec.id} spec={spec} cropLabel={crop ? `${crop.common_name} (${crop.code})` : "—"} />
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function PackSpecificationRow({ spec, cropLabel }: { spec: PackSpecificationRead; cropLabel: string }) {
  const varietiesQuery = useVarieties(spec.crop_id);
  const variety = varietiesQuery.data?.find((v) => v.id === spec.variety_id);
  return (
    <tr className="hover:bg-surface-subtle">
      <td className="px-4 py-2 font-medium text-ink">{spec.code}</td>
      <td className="px-4 py-2 text-ink">{spec.name}</td>
      <td className="px-4 py-2 text-ink-muted">{cropLabel}</td>
      <td className="px-4 py-2 text-ink-muted">
        {spec.variety_id ? (variety ? `${variety.name} (${variety.code})` : "—") : "Any variety"}
      </td>
      <td className="px-4 py-2 text-ink-muted">{spec.customer_reference ?? "—"}</td>
      <td className="px-4 py-2">
        <Link href={`/pack-specifications/${spec.id}`} className="text-sm font-medium text-brand-700 hover:underline">
          View
        </Link>
      </td>
    </tr>
  );
}
