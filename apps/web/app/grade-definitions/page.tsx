"use client";

import { PlusCircle } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Breadcrumbs } from "@/components/Breadcrumbs";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { GradeDefinitionForm } from "@/components/grade-definitions/GradeDefinitionForm";
import { LoadingSkeleton } from "@/components/LoadingSkeleton";
import { PageHeader } from "@/components/PageHeader";
import { StandaloneShell } from "@/components/StandaloneShell";
import { Button } from "@/components/ui/Button";
import type { CropRead, GradeDefinitionCreate, GradeDefinitionRead } from "@/lib/api/client";
import { AppError } from "@/lib/errors/adapter";
import { useAllGradeDefinitions, useCreateGradeDefinition, useCrops, useVarieties } from "@/lib/query/hooks";

function errorMessage(error: unknown): string {
  return error instanceof AppError ? error.message : "Something went wrong. Please try again.";
}

/** PILOT-SETUP-001B7: tenant-scoped commercial-grade master data (no
 * `farm_id` on `GradeDefinition` -- see `grade_definitions.py`'s own model
 * docstring), so this stays a standalone route outside `/farms/[farmId]`,
 * mirroring Crops/Production Systems/Workflows exactly. This list never
 * decorates every row with its active version (that would require an N+1
 * per-row versions request) -- "View" opens the definition's own detail
 * page, which fetches and displays that definition's full version catalog. */
export default function GradeDefinitionsPage() {
  const router = useRouter();
  const [creating, setCreating] = useState(false);
  const [serverError, setServerError] = useState<string | null>(null);

  const definitionsQuery = useAllGradeDefinitions();
  const cropsQuery = useCrops();
  const createMutation = useCreateGradeDefinition();

  const definitions = definitionsQuery.data ?? [];
  const crops = cropsQuery.data ?? [];

  const isLoading = definitionsQuery.isLoading || cropsQuery.isLoading;
  const loadError = definitionsQuery.error ?? cropsQuery.error;

  function handleSubmit(payload: GradeDefinitionCreate) {
    setServerError(null);
    createMutation.mutate(payload, {
      onSuccess: (definition) => router.push(`/grade-definitions/${definition.id}`),
      onError: (error) => setServerError(errorMessage(error)),
    });
  }

  return (
    <StandaloneShell>
      <PageHeader
        title="Grade Definitions"
        breadcrumbs={<Breadcrumbs items={[{ label: "Home", href: "/farms" }, { label: "Grade Definitions" }]} />}
        actions={
          !creating && (
            <Button variant="primary" onClick={() => setCreating(true)}>
              <PlusCircle aria-hidden="true" className="h-4 w-4" />
              New grade definition
            </Button>
          )
        }
      />
      <p className="-mt-3 mb-6 text-xs text-ink-muted">
        Tenant-wide commercial grade classifications. Configuration only -- actual grading of harvested produce
        happens on the Grading screen inside a Farm.
      </p>

      {isLoading && <LoadingSkeleton rows={4} label="Loading grade definitions" />}
      {loadError && (
        <ErrorState
          error={loadError}
          onRetry={() => {
            definitionsQuery.refetch();
            cropsQuery.refetch();
          }}
        />
      )}

      {!isLoading && !loadError && creating && (
        <GradeDefinitionForm
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

      {!isLoading && !loadError && !creating && definitions.length === 0 && (
        <EmptyState
          title="No grade definitions yet"
          description="Create the first commercial grade classification before configuring a Pack Specification against it."
        />
      )}

      {!isLoading && !loadError && !creating && definitions.length > 0 && (
        <GradeDefinitionsTable definitions={definitions} crops={crops} />
      )}
    </StandaloneShell>
  );
}

function GradeDefinitionsTable({
  definitions,
  crops,
}: {
  definitions: GradeDefinitionRead[];
  crops: CropRead[];
}) {
  return (
    <div className="overflow-x-auto rounded-xl border border-border-subtle bg-surface">
      <table className="w-full text-left text-sm">
        <thead className="border-b border-border-subtle bg-surface-subtle text-xs uppercase text-ink-muted">
          <tr>
            <th className="px-4 py-2 font-medium">Code</th>
            <th className="px-4 py-2 font-medium">Name</th>
            <th className="px-4 py-2 font-medium">Crop</th>
            <th className="px-4 py-2 font-medium">Variety</th>
            <th className="px-4 py-2 font-medium" />
          </tr>
        </thead>
        <tbody className="divide-y divide-border-subtle">
          {definitions.map((definition) => {
            const crop = crops.find((c) => c.id === definition.crop_id);
            return (
              <GradeDefinitionRow key={definition.id} definition={definition} cropLabel={crop ? `${crop.common_name} (${crop.code})` : "—"} />
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function GradeDefinitionRow({
  definition,
  cropLabel,
}: {
  definition: GradeDefinitionRead;
  cropLabel: string;
}) {
  const varietiesQuery = useVarieties(definition.crop_id);
  const variety = varietiesQuery.data?.find((v) => v.id === definition.variety_id);
  return (
    <tr className="hover:bg-surface-subtle">
      <td className="px-4 py-2 font-medium text-ink">{definition.code}</td>
      <td className="px-4 py-2 text-ink">{definition.name}</td>
      <td className="px-4 py-2 text-ink-muted">{cropLabel}</td>
      <td className="px-4 py-2 text-ink-muted">
        {definition.variety_id ? (variety ? `${variety.name} (${variety.code})` : "—") : "Any variety"}
      </td>
      <td className="px-4 py-2">
        <Link href={`/grade-definitions/${definition.id}`} className="text-sm font-medium text-brand-700 hover:underline">
          View
        </Link>
      </td>
    </tr>
  );
}
