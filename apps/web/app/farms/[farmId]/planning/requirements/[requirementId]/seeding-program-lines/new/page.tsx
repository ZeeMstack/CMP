"use client";

import { useParams, useRouter } from "next/navigation";
import { useState } from "react";

import { Breadcrumbs } from "@/components/Breadcrumbs";
import { ErrorState } from "@/components/ErrorState";
import { LoadingSkeleton } from "@/components/LoadingSkeleton";
import { PageHeader } from "@/components/PageHeader";
import { SeedingProgramLineForm } from "@/components/planning/SeedingProgramLineForm";
import { AppError } from "@/lib/errors/adapter";
import { useCreateSeedingProgramLine, useProductionRequirement } from "@/lib/query/hooks";

export default function NewSeedingProgramLinePage() {
  const { farmId, requirementId } = useParams<{ farmId: string; requirementId: string }>();
  const router = useRouter();
  const requirementQuery = useProductionRequirement(farmId, requirementId);
  const mutation = useCreateSeedingProgramLine(farmId, requirementId);
  const [serverError, setServerError] = useState<string | null>(null);

  if (requirementQuery.isLoading) {
    return <LoadingSkeleton rows={4} label="Loading production requirement" />;
  }
  if (requirementQuery.error) {
    return <ErrorState error={requirementQuery.error} onRetry={() => requirementQuery.refetch()} />;
  }
  const requirement = requirementQuery.data;
  if (!requirement) return null;

  return (
    <div>
      <PageHeader
        title="Add Plan Line"
        breadcrumbs={
          <Breadcrumbs
            items={[
              { label: "Home", href: `/farms/${farmId}` },
              { label: "Planning", href: `/farms/${farmId}/planning` },
              { label: requirement.code, href: `/farms/${farmId}/planning/requirements/${requirementId}` },
              { label: "Add Plan Line" },
            ]}
          />
        }
      />
      <SeedingProgramLineForm
        cropId={requirement.crop.id}
        cropName={requirement.crop.common_name}
        expectedCoverageUomId={requirement.uom.id}
        expectedCoverageUomCode={requirement.uom.code}
        isSubmitting={mutation.isPending}
        serverError={serverError}
        onSubmit={(payload) => {
          setServerError(null);
          mutation.mutate(payload, {
            onSuccess: () => {
              router.push(`/farms/${farmId}/planning/requirements/${requirementId}`);
            },
            onError: (error) => {
              setServerError(error instanceof AppError ? error.message : "Something went wrong. Please try again.");
            },
          });
        }}
      />
    </div>
  );
}
