"use client";

import { useParams, useRouter, useSearchParams } from "next/navigation";
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
  const searchParams = useSearchParams();
  const mutation = useSowNewBatch(farmId);
  const [serverError, setServerError] = useState<string | null>(null);

  // PLANNING-OPS-001: "Sow Now" from a Seeding Program plan line hands off
  // here via query params -- prefill/context only, never a second Sowing
  // form (the ticket explicitly forbids that).
  const seedingProgramLineId = searchParams.get("seeding_program_line_id");
  const planCropId = searchParams.get("crop_id");
  const planVarietyId = searchParams.get("variety_id");
  const planPrefill =
    seedingProgramLineId && planCropId
      ? { seedingProgramLineId, cropId: planCropId, varietyId: planVarietyId }
      : null;

  return (
    <div>
      <PageHeader
        title="New Sowing"
        breadcrumbs={
          <Breadcrumbs
            items={[
              { label: "Home", href: `/farms/${farmId}` },
              { label: "Nursery Operations" },
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
        planPrefill={planPrefill}
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
