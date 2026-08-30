"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { Breadcrumbs } from "@/components/Breadcrumbs";
import { CreateFarmForm } from "@/components/farms/CreateFarmForm";
import { PageHeader } from "@/components/PageHeader";
import { AppError } from "@/lib/errors/adapter";
import { useCreateFarm } from "@/lib/query/hooks";

export default function NewFarmPage() {
  const router = useRouter();
  const mutation = useCreateFarm();
  const [serverError, setServerError] = useState<string | null>(null);

  return (
    <div className="mx-auto max-w-2xl px-4 py-8">
      <PageHeader
        title="Create Farm"
        breadcrumbs={<Breadcrumbs items={[{ label: "Farms", href: "/farms" }, { label: "Create Farm" }]} />}
      />
      <CreateFarmForm
        isSubmitting={mutation.isPending}
        serverError={serverError}
        onSubmit={(payload) => {
          setServerError(null);
          mutation.mutate(payload, {
            onSuccess: (farm) => {
              router.push(`/farms/${farm.id}/farm-setup`);
            },
            onError: (error) => {
              if (error instanceof AppError && error.kind === "permission_error") {
                setServerError("You do not have permission to create farms for this tenant.");
                return;
              }
              setServerError(error instanceof AppError ? error.message : "Something went wrong. Please try again.");
            },
          });
        }}
      />
    </div>
  );
}
