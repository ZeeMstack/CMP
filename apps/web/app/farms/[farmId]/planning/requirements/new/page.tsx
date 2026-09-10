"use client";

import { useParams, useRouter } from "next/navigation";
import { useState } from "react";

import { Breadcrumbs } from "@/components/Breadcrumbs";
import { PageHeader } from "@/components/PageHeader";
import { RequirementForm } from "@/components/planning/RequirementForm";
import { AppError } from "@/lib/errors/adapter";
import { useCreateProductionRequirement } from "@/lib/query/hooks";

export default function NewProductionRequirementPage() {
  const { farmId } = useParams<{ farmId: string }>();
  const router = useRouter();
  const mutation = useCreateProductionRequirement(farmId);
  const [serverError, setServerError] = useState<string | null>(null);

  return (
    <div>
      <PageHeader
        title="New Production Requirement"
        breadcrumbs={
          <Breadcrumbs
            items={[
              { label: "Home", href: `/farms/${farmId}` },
              { label: "Planning", href: `/farms/${farmId}/planning` },
              { label: "New Production Requirement" },
            ]}
          />
        }
      />
      <RequirementForm
        isSubmitting={mutation.isPending}
        serverError={serverError}
        onSubmit={(payload) => {
          setServerError(null);
          mutation.mutate(payload, {
            onSuccess: (result) => {
              router.push(`/farms/${farmId}/planning/requirements/${result.id}`);
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
