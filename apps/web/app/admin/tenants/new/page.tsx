"use client";

import { useState } from "react";

import { CreateTenantForm } from "@/components/admin/CreateTenantForm";
import { TenantOnboardingConfirmation } from "@/components/admin/TenantOnboardingConfirmation";
import { Breadcrumbs } from "@/components/Breadcrumbs";
import { PageHeader } from "@/components/PageHeader";
import type { PlatformTenantOnboardingResponse } from "@/lib/api/client";
import { AppError } from "@/lib/errors/adapter";
import { useCreatePlatformTenant } from "@/lib/query/hooks";

export default function NewPlatformTenantPage() {
  const mutation = useCreatePlatformTenant();
  const [serverError, setServerError] = useState<string | null>(null);
  const [result, setResult] = useState<PlatformTenantOnboardingResponse | null>(null);
  // Bumped on "Create Another Tenant" to force CreateTenantForm to remount
  // with fresh react-hook-form state, rather than reset() fighting whatever
  // internal state the form still holds.
  const [formKey, setFormKey] = useState(0);

  if (result) {
    return (
      <div>
        <PageHeader
          title="Tenant created"
          breadcrumbs={
            <Breadcrumbs
              items={[
                { label: "Platform Administration" },
                { label: "Tenants", href: "/admin/tenants" },
                { label: "Tenant created" },
              ]}
            />
          }
        />
        <TenantOnboardingConfirmation
          result={result}
          onCreateAnother={() => {
            setResult(null);
            setServerError(null);
            setFormKey((key) => key + 1);
          }}
        />
      </div>
    );
  }

  return (
    <div>
      <PageHeader
        title="Create Tenant"
        breadcrumbs={
          <Breadcrumbs
            items={[
              { label: "Platform Administration" },
              { label: "Tenants", href: "/admin/tenants" },
              { label: "Create Tenant" },
            ]}
          />
        }
      />
      <CreateTenantForm
        key={formKey}
        isSubmitting={mutation.isPending}
        serverError={serverError}
        onSubmit={(payload) => {
          setServerError(null);
          mutation.mutate(payload, {
            onSuccess: (response) => setResult(response),
            onError: (error) => {
              if (error instanceof AppError && error.kind === "permission_error") {
                setServerError("You do not have platform administrator access.");
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
