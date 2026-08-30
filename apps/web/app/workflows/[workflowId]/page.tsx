"use client";

import { useParams, useRouter } from "next/navigation";
import { useState } from "react";

import { Breadcrumbs } from "@/components/Breadcrumbs";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { LoadingSkeleton } from "@/components/LoadingSkeleton";
import { PageHeader } from "@/components/PageHeader";
import { StandaloneShell } from "@/components/StandaloneShell";
import { StatusBadge, type StatusTone } from "@/components/StatusBadge";
import { Button } from "@/components/ui/Button";
import { AppError } from "@/lib/errors/adapter";
import {
  useCreateWorkflowDraftVersion,
  useCrops,
  useProductionSystems,
  useVarieties,
  useWorkflow,
  useWorkflowVersions,
} from "@/lib/query/hooks";

function errorMessage(error: unknown): string {
  return error instanceof AppError ? error.message : "Something went wrong. Please try again.";
}

function versionStateTone(state: string): StatusTone {
  if (state === "published") return "active";
  if (state === "draft") return "attention";
  return "closed";
}

function versionActionLabel(state: string): string {
  if (state === "draft") return "Resume Draft";
  if (state === "published") return "View Published Version";
  return "View Retired Version";
}

/** PILOT-SETUP-001B6A: this Workflow's own shell fields come from
 * `GET /workflows/{id}`, and its full version catalog -- every draft,
 * published, and retired row, truthfully, in the backend's own ascending
 * order -- from `GET /workflows/{id}/versions`. This is what makes an
 * unfinished draft rediscoverable after navigating away: B6's own version
 * editor route (`/workflows/[workflowId]/versions/[versionId]`) already
 * renders published/retired versions read-only (no edit controls once
 * `state !== "draft"`), so "View Published/Retired Version" reuses that
 * same page unchanged -- only the entry point (this catalog) is new.
 *
 * The backend does not forbid more than one concurrent draft version (no
 * uniqueness constraint on `state = 'draft'`, only on `version_number`), so
 * every draft present is listed and resumable here -- never silently
 * collapsed to "the" draft. "Create new draft version" is still offered
 * once at least one version exists, but only as a secondary action below
 * the catalog (never the primary CTA when a draft is already resumable),
 * so a draft in progress is never accidentally duplicated. */
export default function WorkflowShellPage() {
  const { workflowId } = useParams<{ workflowId: string }>();
  const router = useRouter();
  const [actionError, setActionError] = useState<string | null>(null);

  const workflowQuery = useWorkflow(workflowId);
  const versionsQuery = useWorkflowVersions(workflowId);
  const cropsQuery = useCrops();
  const productionSystemsQuery = useProductionSystems();
  const createDraftVersion = useCreateWorkflowDraftVersion();

  const workflow = workflowQuery.data;
  const versions = versionsQuery.data ?? [];
  const crop = cropsQuery.data?.find((c) => c.id === workflow?.crop_id);
  const productionSystem = productionSystemsQuery.data?.find((p) => p.id === workflow?.production_system_id);
  const varietiesQuery = useVarieties(workflow?.crop_id);
  const variety = varietiesQuery.data?.find((v) => v.id === workflow?.variety_id);

  const isLoading =
    workflowQuery.isLoading || versionsQuery.isLoading || cropsQuery.isLoading || productionSystemsQuery.isLoading;
  const loadError = workflowQuery.error ?? versionsQuery.error ?? cropsQuery.error ?? productionSystemsQuery.error;

  const hasDraft = versions.some((v) => v.state === "draft");

  function handleCreateDraftVersion() {
    if (!workflow) return;
    setActionError(null);
    createDraftVersion.mutate(workflow.id, {
      onSuccess: (version) => router.push(`/workflows/${workflow.id}/versions/${version.id}`),
      onError: (error) => setActionError(errorMessage(error)),
    });
  }

  return (
    <StandaloneShell>
      <PageHeader
        title={workflow ? workflow.name : "Workflow"}
        breadcrumbs={
          <Breadcrumbs
            items={[
              { label: "Home", href: "/farms" },
              { label: "Workflows", href: "/workflows" },
              { label: workflow?.name ?? "Workflow" },
            ]}
          />
        }
      />

      {isLoading && <LoadingSkeleton rows={4} label="Loading workflow" />}
      {loadError && (
        <ErrorState
          error={loadError}
          onRetry={() => {
            workflowQuery.refetch();
            versionsQuery.refetch();
            cropsQuery.refetch();
            productionSystemsQuery.refetch();
          }}
        />
      )}
      {!isLoading && !loadError && !workflow && (
        <ErrorState error={new AppError("not_found", "This workflow could not be found.")} />
      )}

      {!isLoading && !loadError && workflow && (
        <div className="flex flex-col gap-6">
          <dl className="grid grid-cols-1 gap-4 rounded-xl border border-border-subtle bg-surface p-4 sm:grid-cols-2">
            <div>
              <dt className="text-xs font-medium uppercase text-ink-muted">Code</dt>
              <dd className="text-sm text-ink">{workflow.code}</dd>
            </div>
            <div>
              <dt className="text-xs font-medium uppercase text-ink-muted">Crop</dt>
              <dd className="text-sm text-ink">{crop ? `${crop.common_name} (${crop.code})` : "—"}</dd>
            </div>
            <div>
              <dt className="text-xs font-medium uppercase text-ink-muted">Variety</dt>
              <dd className="text-sm text-ink">
                {workflow.variety_id ? (variety ? `${variety.name} (${variety.code})` : "—") : "Any variety"}
              </dd>
            </div>
            <div>
              <dt className="text-xs font-medium uppercase text-ink-muted">Production system</dt>
              <dd className="text-sm text-ink">
                {productionSystem ? `${productionSystem.name} (${productionSystem.code})` : "—"}
              </dd>
            </div>
          </dl>

          <section aria-labelledby="versions-heading">
            <h2 id="versions-heading" className="mb-3 text-sm font-semibold uppercase tracking-wide text-ink-muted">
              Versions
            </h2>

            {actionError && (
              <p role="alert" className="mb-3 text-xs text-red-700">
                {actionError}
              </p>
            )}

            {versions.length === 0 ? (
              <EmptyState
                title="No versions yet"
                description="Create the first draft version to start configuring stages and transitions."
                action={
                  <Button variant="primary" onClick={handleCreateDraftVersion} disabled={createDraftVersion.isPending}>
                    {createDraftVersion.isPending ? "Creating…" : "Create draft version"}
                  </Button>
                }
              />
            ) : (
              <>
                <div className="overflow-x-auto rounded-xl border border-border-subtle bg-surface">
                  <table className="w-full text-left text-sm">
                    <thead className="border-b border-border-subtle bg-surface-subtle text-xs uppercase text-ink-muted">
                      <tr>
                        <th className="px-4 py-2 font-medium">Version</th>
                        <th className="px-4 py-2 font-medium">State</th>
                        <th className="px-4 py-2 font-medium">Created</th>
                        <th className="px-4 py-2 font-medium">Published</th>
                        <th className="px-4 py-2 font-medium" />
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-border-subtle">
                      {versions.map((version) => {
                        const tone: StatusTone = versionStateTone(version.state);
                        return (
                          <tr key={version.id} className="hover:bg-surface-subtle">
                            <td className="px-4 py-2 font-medium text-ink">v{version.version_number}</td>
                            <td className="px-4 py-2">
                              <StatusBadge
                                label={version.state.charAt(0).toUpperCase() + version.state.slice(1)}
                                tone={tone}
                              />
                            </td>
                            <td className="px-4 py-2 text-ink-muted">
                              {new Date(version.created_at).toLocaleString()}
                            </td>
                            <td className="px-4 py-2 text-ink-muted">
                              {version.published_at ? new Date(version.published_at).toLocaleString() : "—"}
                            </td>
                            <td className="px-4 py-2">
                              <Button
                                variant={version.state === "draft" ? "primary" : "secondary"}
                                onClick={() => router.push(`/workflows/${workflow.id}/versions/${version.id}`)}
                              >
                                {versionActionLabel(version.state)}
                              </Button>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>

                {!hasDraft && (
                  <div className="mt-4">
                    <Button variant="secondary" onClick={handleCreateDraftVersion} disabled={createDraftVersion.isPending}>
                      {createDraftVersion.isPending ? "Creating…" : "Create new draft version"}
                    </Button>
                  </div>
                )}
              </>
            )}
          </section>
        </div>
      )}
    </StandaloneShell>
  );
}
