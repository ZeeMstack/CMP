"use client";

import { useParams, useRouter } from "next/navigation";
import { useState } from "react";

import { Breadcrumbs } from "@/components/Breadcrumbs";
import { NurseryJourney } from "@/components/nursery/NurseryJourney";
import { PageHeader } from "@/components/PageHeader";
import { SowingForm } from "@/components/nursery/SowingForm";
import { AppError } from "@/lib/errors/adapter";
import { useSowNewBatch } from "@/lib/query/hooks";

export default function NewSowingPage() {
  const { farmId } = useParams<{ farmId: string }>();
  const router = useRouter();
  const mutation = useSowNewBatch(farmId);
  const [serverError, setServerError] = useState<string | null>(null);

  return (
    <div>
      <PageHeader
        title="New Sowing"
        breadcrumbs={
          <Breadcrumbs
            items={[
              { label: "Home", href: `/farms/${farmId}` },
              { label: "Batches", href: `/farms/${farmId}/crop-batches` },
              { label: "New Sowing" },
            ]}
          />
        }
      />
      <NurseryJourney farmId={farmId} current="seeding" />
      <SowingForm
        farmId={farmId}
        isSubmitting={mutation.isPending}
        serverError={serverError}
        onSubmit={(payload) => {
          setServerError(null);
          mutation.mutate(payload, {
            onSuccess: (result) => {
              router.push(`/farms/${farmId}/crop-batches/${result.batch_id}?tab=sowing`);
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
