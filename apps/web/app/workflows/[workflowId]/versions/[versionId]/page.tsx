"use client";

import { useParams } from "next/navigation";
import { useState } from "react";

import { Breadcrumbs } from "@/components/Breadcrumbs";
import { ErrorState } from "@/components/ErrorState";
import { LoadingSkeleton } from "@/components/LoadingSkeleton";
import { PageHeader } from "@/components/PageHeader";
import { StandaloneShell } from "@/components/StandaloneShell";
import { StatusBadge, type StatusTone } from "@/components/StatusBadge";
import { Button } from "@/components/ui/Button";
import { WorkflowStageForm } from "@/components/workflows/WorkflowStageForm";
import { WorkflowTransitionForm } from "@/components/workflows/WorkflowTransitionForm";
import type { WorkflowStageCreate, WorkflowTransitionCreate } from "@/lib/api/client";
import { AppError } from "@/lib/errors/adapter";
import {
  useAddWorkflowStage,
  useAddWorkflowTransition,
  useCarrierTypes,
  useCrops,
  usePublishWorkflowVersion,
  useProductionSystems,
  useVarieties,
  useWorkflow,
  useWorkflowVersion,
} from "@/lib/query/hooks";

function errorMessage(error: unknown): string {
  return error instanceof AppError ? error.message : "Something went wrong. Please try again.";
}

const STAGE_CATEGORY_LABELS: Record<string, string> = {
  seeding: "Seeding",
  germination: "Germination",
  nursery: "Nursery",
  transplanting: "Transplanting",
  intermediate: "Intermediate",
  production: "Production",
  harvest_ready: "Harvest ready",
  harvesting: "Harvesting",
  completed: "Completed",
  rejected: "Rejected",
};

function versionStateTone(state: string): StatusTone {
  if (state === "published") return "active";
  if (state === "draft") return "attention";
  return "closed";
}

/** PILOT-SETUP-001B6 / B6A: the one screen where Stages, Transitions, and
 * Publish all happen, against the WorkflowVersion whose id this URL
 * carries. Reachable two ways: directly after creating/publishing a
 * version (this session's own navigation), or -- since B6A closed the
 * resumability gap -- via this workflow's own shell page
 * (`/workflows/[workflowId]`), whose version catalog now lists every
 * draft/published/retired version and links back here for each. Every
 * mutating action is disabled once `state !== "draft"` (published/retired
 * versions are immutable here, matching the backend's own
 * `WorkflowVersionNotDraftError`) -- publishing is always an explicit
 * button press, never automatic. */
export default function WorkflowVersionEditorPage() {
  const { workflowId, versionId } = useParams<{ workflowId: string; versionId: string }>();

  const [addingStage, setAddingStage] = useState(false);
  const [addingTransition, setAddingTransition] = useState(false);
  const [stageError, setStageError] = useState<string | null>(null);
  const [transitionError, setTransitionError] = useState<string | null>(null);
  const [publishError, setPublishError] = useState<string | null>(null);

  const workflowQuery = useWorkflow(workflowId);
  const versionQuery = useWorkflowVersion(workflowId, versionId);
  const carrierTypesQuery = useCarrierTypes();
  const cropsQuery = useCrops();
  const productionSystemsQuery = useProductionSystems();

  const workflow = workflowQuery.data;
  const crop = cropsQuery.data?.find((c) => c.id === workflow?.crop_id);
  const productionSystem = productionSystemsQuery.data?.find((p) => p.id === workflow?.production_system_id);
  const varietiesQuery = useVarieties(workflow?.crop_id);
  const variety = varietiesQuery.data?.find((v) => v.id === workflow?.variety_id);

  const addStage = useAddWorkflowStage(workflowId, versionId);
  const addTransition = useAddWorkflowTransition(workflowId, versionId);
  const publish = usePublishWorkflowVersion(workflowId, versionId);

  const version = versionQuery.data;
  const stages = version?.stages ?? [];
  const transitions = version?.transitions ?? [];
  const carrierTypes = carrierTypesQuery.data ?? [];
  const isDraft = version?.state === "draft";

  const isLoading = workflowQuery.isLoading || versionQuery.isLoading;
  const loadError = workflowQuery.error ?? versionQuery.error;

  function stageName(stageId: string): string {
    const stage = stages.find((s) => s.id === stageId);
    return stage ? `${stage.name} (${stage.code})` : stageId;
  }

  function carrierTypeName(carrierTypeId: string | null): string {
    if (!carrierTypeId) return "—";
    const type = carrierTypes.find((t) => t.id === carrierTypeId);
    return type ? type.name : "—";
  }

  function handleAddStage(payload: WorkflowStageCreate) {
    setStageError(null);
    addStage.mutate(payload, {
      onSuccess: () => setAddingStage(false),
      onError: (error) => setStageError(errorMessage(error)),
    });
  }

  function handleAddTransition(payload: WorkflowTransitionCreate) {
    setTransitionError(null);
    addTransition.mutate(payload, {
      onSuccess: () => setAddingTransition(false),
      onError: (error) => setTransitionError(errorMessage(error)),
    });
  }

  function handlePublish() {
    setPublishError(null);
    publish.mutate(undefined, {
      onError: (error) => setPublishError(errorMessage(error)),
    });
  }

  return (
    <StandaloneShell>
      <PageHeader
        title={workflow ? `${workflow.name} — v${version?.version_number ?? "…"}` : "Workflow version"}
        breadcrumbs={
          <Breadcrumbs
            items={[
              { label: "Home", href: "/farms" },
              { label: "Workflows", href: "/workflows" },
              { label: workflow?.name ?? "Workflow", href: workflow ? `/workflows/${workflow.id}` : undefined },
              { label: version ? `Version ${version.version_number}` : "Version" },
            ]}
          />
        }
      />

      {isLoading && <LoadingSkeleton rows={6} label="Loading workflow version" />}
      {loadError && (
        <ErrorState
          error={loadError}
          onRetry={() => {
            workflowQuery.refetch();
            versionQuery.refetch();
          }}
        />
      )}
      {!isLoading && !loadError && (!workflow || !version) && (
        <ErrorState error={new AppError("not_found", "This workflow version could not be found.")} />
      )}

      {!isLoading && !loadError && workflow && version && (
        <div className="flex flex-col gap-8">
          {/* Overview */}
          <section aria-labelledby="overview-heading">
            <h2 id="overview-heading" className="mb-3 text-sm font-semibold uppercase tracking-wide text-ink-muted">
              Overview
            </h2>
            <dl className="grid grid-cols-1 gap-4 rounded-xl border border-border-subtle bg-surface p-4 sm:grid-cols-3">
              <div>
                <dt className="text-xs font-medium uppercase text-ink-muted">Workflow</dt>
                <dd className="text-sm text-ink">
                  {workflow.name} ({workflow.code})
                </dd>
              </div>
              <div>
                <dt className="text-xs font-medium uppercase text-ink-muted">Crop / Variety</dt>
                <dd className="text-sm text-ink">
                  {crop?.common_name ?? "—"}
                  {workflow.variety_id ? ` / ${variety?.name ?? "…"}` : " / Any variety"}
                </dd>
              </div>
              <div>
                <dt className="text-xs font-medium uppercase text-ink-muted">Production system</dt>
                <dd className="text-sm text-ink">{productionSystem?.name ?? "—"}</dd>
              </div>
              <div>
                <dt className="text-xs font-medium uppercase text-ink-muted">Version</dt>
                <dd className="text-sm text-ink">{version.version_number}</dd>
              </div>
              <div>
                <dt className="text-xs font-medium uppercase text-ink-muted">State</dt>
                <dd>
                  <StatusBadge
                    label={version.state.charAt(0).toUpperCase() + version.state.slice(1)}
                    tone={versionStateTone(version.state)}
                  />
                </dd>
              </div>
              <div>
                <dt className="text-xs font-medium uppercase text-ink-muted">Published at</dt>
                <dd className="text-sm text-ink">
                  {version.published_at ? new Date(version.published_at).toLocaleString() : "—"}
                </dd>
              </div>
            </dl>
          </section>

          {/* Stages */}
          <section aria-labelledby="stages-heading">
            <div className="mb-3 flex items-center justify-between">
              <h2 id="stages-heading" className="text-sm font-semibold uppercase tracking-wide text-ink-muted">
                Stages
              </h2>
              {isDraft && !addingStage && (
                <Button variant="secondary" onClick={() => setAddingStage(true)}>
                  Add stage
                </Button>
              )}
            </div>

            {!isDraft && (
              <p className="mb-3 text-xs text-ink-muted">
                This version is {version.state} -- stages can no longer be added.
              </p>
            )}

            {addingStage && (
              <div className="mb-4">
                <WorkflowStageForm
                  carrierTypes={carrierTypes}
                  nextDisplayOrder={stages.length}
                  isSubmitting={addStage.isPending}
                  serverError={stageError}
                  onCancel={() => {
                    setAddingStage(false);
                    setStageError(null);
                  }}
                  onSubmit={handleAddStage}
                />
              </div>
            )}

            {stages.length === 0 ? (
              <p className="text-sm text-ink-muted">No stages yet.</p>
            ) : (
              <div className="overflow-x-auto rounded-xl border border-border-subtle bg-surface">
                <table className="w-full text-left text-sm">
                  <thead className="border-b border-border-subtle bg-surface-subtle text-xs uppercase text-ink-muted">
                    <tr>
                      <th className="px-4 py-2 font-medium">Order</th>
                      <th className="px-4 py-2 font-medium">Code</th>
                      <th className="px-4 py-2 font-medium">Name</th>
                      <th className="px-4 py-2 font-medium">Category</th>
                      <th className="px-4 py-2 font-medium">Duration (min)</th>
                      <th className="px-4 py-2 font-medium">Required carrier</th>
                      <th className="px-4 py-2 font-medium">Start</th>
                      <th className="px-4 py-2 font-medium">Terminal</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border-subtle">
                    {[...stages]
                      .sort((a, b) => a.display_order - b.display_order)
                      .map((stage) => (
                        <tr key={stage.id} className="hover:bg-surface-subtle">
                          <td className="px-4 py-2 text-ink-muted">{stage.display_order}</td>
                          <td className="px-4 py-2 font-medium text-ink">{stage.code}</td>
                          <td className="px-4 py-2 text-ink">{stage.name}</td>
                          <td className="px-4 py-2 text-ink-muted">
                            {STAGE_CATEGORY_LABELS[stage.stage_category] ?? stage.stage_category}
                          </td>
                          <td className="px-4 py-2 text-ink-muted">{stage.expected_duration_minutes ?? "—"}</td>
                          <td className="px-4 py-2 text-ink-muted">
                            {carrierTypeName(stage.required_carrier_type_id)}
                          </td>
                          <td className="px-4 py-2 text-ink-muted">{stage.is_start ? "Yes" : "—"}</td>
                          <td className="px-4 py-2 text-ink-muted">{stage.is_terminal ? "Yes" : "—"}</td>
                        </tr>
                      ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          {/* Transitions */}
          <section aria-labelledby="transitions-heading">
            <div className="mb-3 flex items-center justify-between">
              <h2 id="transitions-heading" className="text-sm font-semibold uppercase tracking-wide text-ink-muted">
                Transitions
              </h2>
              {isDraft && !addingTransition && stages.length >= 2 && (
                <Button variant="secondary" onClick={() => setAddingTransition(true)}>
                  Add transition
                </Button>
              )}
            </div>

            {isDraft && stages.length < 2 && (
              <p className="mb-3 text-xs text-ink-muted">Add at least two stages before configuring a transition.</p>
            )}
            {!isDraft && (
              <p className="mb-3 text-xs text-ink-muted">
                This version is {version.state} -- transitions can no longer be added.
              </p>
            )}

            {addingTransition && (
              <div className="mb-4">
                <WorkflowTransitionForm
                  stages={stages}
                  isSubmitting={addTransition.isPending}
                  serverError={transitionError}
                  onCancel={() => {
                    setAddingTransition(false);
                    setTransitionError(null);
                  }}
                  onSubmit={handleAddTransition}
                />
              </div>
            )}

            {transitions.length === 0 ? (
              <p className="text-sm text-ink-muted">No transitions yet.</p>
            ) : (
              <div className="overflow-x-auto rounded-xl border border-border-subtle bg-surface">
                <table className="w-full text-left text-sm">
                  <thead className="border-b border-border-subtle bg-surface-subtle text-xs uppercase text-ink-muted">
                    <tr>
                      <th className="px-4 py-2 font-medium">Code</th>
                      <th className="px-4 py-2 font-medium">Name</th>
                      <th className="px-4 py-2 font-medium">From</th>
                      <th className="px-4 py-2 font-medium">To</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border-subtle">
                    {transitions.map((transition) => (
                      <tr key={transition.id} className="hover:bg-surface-subtle">
                        <td className="px-4 py-2 font-medium text-ink">{transition.code}</td>
                        <td className="px-4 py-2 text-ink">{transition.name}</td>
                        <td className="px-4 py-2 text-ink-muted">{stageName(transition.from_stage_id)}</td>
                        <td className="px-4 py-2 text-ink-muted">{stageName(transition.to_stage_id)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          {/* Review & publish */}
          <section aria-labelledby="publish-heading">
            <h2 id="publish-heading" className="mb-3 text-sm font-semibold uppercase tracking-wide text-ink-muted">
              Review &amp; publish
            </h2>
            <div className="rounded-xl border border-border-subtle bg-surface p-4">
              <ul className="mb-4 flex flex-col gap-1 text-sm text-ink">
                <li>
                  Workflow: {workflow.name} ({workflow.code})
                </li>
                <li>Production system: {productionSystem?.name ?? "—"}</li>
                <li>Stage count: {stages.length}</li>
                <li>Transition count: {transitions.length}</li>
              </ul>

              {version.state === "published" && (
                <p role="status" className="mb-4 rounded-md bg-brand-100 px-3 py-2 text-sm text-brand-800">
                  Published as version {version.version_number}
                  {version.published_at ? ` on ${new Date(version.published_at).toLocaleString()}` : ""}. This
                  version is now immutable; create a new draft version to make further changes.
                </p>
              )}
              {version.state === "retired" && (
                <p role="status" className="mb-4 rounded-md bg-surface-subtle px-3 py-2 text-sm text-ink-muted">
                  This version was retired when a later version was published.
                </p>
              )}
              {publishError && (
                <p role="alert" className="mb-4 text-xs text-red-700">
                  {publishError}
                </p>
              )}

              {isDraft && (
                <Button variant="primary" onClick={handlePublish} disabled={publish.isPending}>
                  {publish.isPending ? "Publishing…" : "Publish this version"}
                </Button>
              )}
            </div>
          </section>
        </div>
      )}
    </StandaloneShell>
  );
}
