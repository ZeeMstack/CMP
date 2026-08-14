"use client";

import { useParams, useRouter } from "next/navigation";
import { useState } from "react";

import { Breadcrumbs } from "@/components/Breadcrumbs";
import { GreenhouseSetupForm } from "@/components/farm-setup/GreenhouseSetupForm";
import { PageHeader } from "@/components/PageHeader";
import { AppError } from "@/lib/errors/adapter";
import { useCreateGreenhouseSetup } from "@/lib/query/hooks";

export default function NewGreenhouseSetupPage() {
  const { farmId } = useParams<{ farmId: string }>();
  const router = useRouter();
  const mutation = useCreateGreenhouseSetup(farmId);
  const [serverError, setServerError] = useState<string | null>(null);

  return (
    <div>
      <PageHeader
        title="Add greenhouse"
        breadcrumbs={
          <Breadcrumbs
            items={[
              { label: "Home", href: `/farms/${farmId}` },
              { label: "Farm Setup", href: `/farms/${farmId}/farm-setup` },
              { label: "Add greenhouse" },
            ]}
          />
        }
      />
      <GreenhouseSetupForm
        isSubmitting={mutation.isPending}
        serverError={serverError}
        onSubmit={(payload) => {
          setServerError(null);
          mutation.mutate(payload, {
            onSuccess: (result) => {
              router.push(`/farms/${farmId}/farm-setup/${result.greenhouse_id}`);
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
