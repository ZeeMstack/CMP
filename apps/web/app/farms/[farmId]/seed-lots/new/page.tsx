"use client";

import { useParams, useRouter } from "next/navigation";
import { useState } from "react";

import { Breadcrumbs } from "@/components/Breadcrumbs";
import { PageHeader } from "@/components/PageHeader";
import { SeedLotForm } from "@/components/nursery/SeedLotForm";
import { AppError } from "@/lib/errors/adapter";
import { useRegisterSeedLot } from "@/lib/query/hooks";

export default function NewSeedLotPage() {
  const { farmId } = useParams<{ farmId: string }>();
  const router = useRouter();
  const mutation = useRegisterSeedLot(farmId);
  const [serverError, setServerError] = useState<string | null>(null);

  return (
    <div>
      <PageHeader
        title="Add Seed Lot"
        breadcrumbs={
          <Breadcrumbs
            items={[
              { label: "Home", href: `/farms/${farmId}` },
              { label: "Seed Lots", href: `/farms/${farmId}/seed-lots` },
              { label: "Add Seed Lot" },
            ]}
          />
        }
      />
      <SeedLotForm
        isSubmitting={mutation.isPending}
        serverError={serverError}
        onSubmit={(payload) => {
          setServerError(null);
          mutation.mutate(payload, {
            onSuccess: (result) => {
              router.push(`/farms/${farmId}/seed-lots/${result.id}`);
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
