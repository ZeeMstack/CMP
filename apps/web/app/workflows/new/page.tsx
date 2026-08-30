"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { Breadcrumbs } from "@/components/Breadcrumbs";
import { ErrorState } from "@/components/ErrorState";
import { LoadingSkeleton } from "@/components/LoadingSkeleton";
import { PageHeader } from "@/components/PageHeader";
import { StandaloneShell } from "@/components/StandaloneShell";
import type { WorkflowCreate } from "@/lib/api/client";
import { WorkflowForm } from "@/components/workflows/WorkflowForm";
import { AppError } from "@/lib/errors/adapter";
import { useCreateWorkflow, useCreateWorkflowDraftVersion, useCrops, useProductionSystems } from "@/lib/query/hooks";

function errorMessage(error: unknown): string {
  return error instanceof AppError ? error.message : "Something went wrong. Please try again.";
}

/** PILOT-SETUP-001B6: creates the Workflow shell, then immediately creates
 * its first draft WorkflowVersion (version 1) -- a Workflow with no version
 * cannot be configured with Stages/Transitions at all, so this is the
 * natural continuation of "New Workflow", not a hidden/implicit action. If
 * the draft-version call fails after the Workflow itself was created, this
 * still routes to the Workflow's own detail page, which offers "Create
 * Draft Version" as a retry -- the Workflow is never left unreachable. */
export default function NewWorkflowPage() {
  const router = useRouter();
  const [serverError, setServerError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const cropsQuery = useCrops();
  const productionSystemsQuery = useProductionSystems();
  const createWorkflow = useCreateWorkflow();
  const createDraftVersion = useCreateWorkflowDraftVersion();

  const crops = cropsQuery.data ?? [];
  const productionSystems = productionSystemsQuery.data ?? [];
  const isLoading = cropsQuery.isLoading || productionSystemsQuery.isLoading;
  const loadError = cropsQuery.error ?? productionSystemsQuery.error;

  async function handleSubmit(payload: WorkflowCreate) {
    setServerError(null);
    setIsSubmitting(true);
    try {
      const workflow = await createWorkflow.mutateAsync(payload);
      try {
        const version = await createDraftVersion.mutateAsync(workflow.id);
        router.push(`/workflows/${workflow.id}/versions/${version.id}`);
      } catch {
        router.push(`/workflows/${workflow.id}`);
      }
    } catch (error) {
      setServerError(errorMessage(error));
      setIsSubmitting(false);
    }
  }

  return (
    <StandaloneShell>
      <PageHeader
        title="New Workflow"
        breadcrumbs={
          <Breadcrumbs
            items={[{ label: "Home", href: "/farms" }, { label: "Workflows", href: "/workflows" }, { label: "New" }]}
          />
        }
      />

      {isLoading && <LoadingSkeleton rows={4} label="Loading crops and production systems" />}
      {loadError && (
        <ErrorState
          error={loadError}
          onRetry={() => {
            cropsQuery.refetch();
            productionSystemsQuery.refetch();
          }}
        />
      )}

      {!isLoading && !loadError && crops.length === 0 && (
        <ErrorState
          error={new AppError("invalid_request", "Register at least one crop before creating a workflow.")}
        />
      )}
      {!isLoading && !loadError && crops.length > 0 && productionSystems.length === 0 && (
        <ErrorState
          error={new AppError(
            "invalid_request",
            "Register at least one production system before creating a workflow.",
          )}
        />
      )}

      {!isLoading && !loadError && crops.length > 0 && productionSystems.length > 0 && (
        <WorkflowForm
          crops={crops}
          productionSystems={productionSystems}
          isSubmitting={isSubmitting}
          serverError={serverError}
          onCancel={() => router.push("/workflows")}
          onSubmit={handleSubmit}
        />
      )}
    </StandaloneShell>
  );
}
