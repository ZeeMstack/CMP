"use client";

import { useParams } from "next/navigation";
import { useState } from "react";

import { Breadcrumbs } from "@/components/Breadcrumbs";
import { EmptyState } from "@/components/EmptyState";
import { EffectiveTimeActionPanel } from "@/components/EffectiveTimeActionPanel";
import { ErrorState } from "@/components/ErrorState";
import { GradeDefinitionVersionForm } from "@/components/grade-definitions/GradeDefinitionVersionForm";
import { LoadingSkeleton } from "@/components/LoadingSkeleton";
import { PageHeader } from "@/components/PageHeader";
import { StandaloneShell } from "@/components/StandaloneShell";
import { StatusBadge, type StatusTone } from "@/components/StatusBadge";
import { Button } from "@/components/ui/Button";
import type { GradeDefinitionVersionRead } from "@/lib/api/client";
import { AppError } from "@/lib/errors/adapter";
import {
  useActivateGradeDefinitionVersion,
  useAllGradeDefinitions,
  useCreateGradeDefinitionVersion,
  useCrops,
  useGradeDefinitionVersions,
  useRetireGradeDefinitionVersion,
  useVarieties,
} from "@/lib/query/hooks";

function errorMessage(error: unknown): string {
  return error instanceof AppError ? error.message : "Something went wrong. Please try again.";
}

function versionTone(status: string): StatusTone {
  if (status === "active") return "active";
  if (status === "draft") return "attention";
  return "closed";
}

type ActionState = { kind: "create" } | { kind: "activate"; version: GradeDefinitionVersionRead } | { kind: "retire"; version: GradeDefinitionVersionRead } | null;

/** PILOT-SETUP-001B7: this Grade Definition's own identity is found in the
 * already-cached tenant-wide list (`useAllGradeDefinitions`, shared with the
 * Grading operator picker) rather than a second `GET /grade-definitions/{id}`
 * request -- mirrors `CropVarietiesPage`'s own documented rationale exactly.
 * The version catalog (`useGradeDefinitionVersions`) lists every version
 * regardless of lifecycle status, so a draft created in an earlier visit is
 * always rediscoverable here, never silently dropped. Only one lifecycle
 * action (create draft / activate / retire) is ever open at a time, and
 * every one of them requires an explicit confirm -- creating a version never
 * activates it, and activating never happens without a reviewed
 * `effective_time`. */
export default function GradeDefinitionDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [action, setAction] = useState<ActionState>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const definitionsQuery = useAllGradeDefinitions();
  const versionsQuery = useGradeDefinitionVersions(id);
  const cropsQuery = useCrops();
  const createVersion = useCreateGradeDefinitionVersion(id);
  const activateVersion = useActivateGradeDefinitionVersion(id);
  const retireVersion = useRetireGradeDefinitionVersion(id);

  const definition = definitionsQuery.data?.find((d) => d.id === id);
  const versions = versionsQuery.data ?? [];
  const crop = cropsQuery.data?.find((c) => c.id === definition?.crop_id);
  const varietiesQuery = useVarieties(definition?.crop_id);
  const variety = varietiesQuery.data?.find((v) => v.id === definition?.variety_id);

  const isLoading = definitionsQuery.isLoading || versionsQuery.isLoading || cropsQuery.isLoading;
  const loadError = definitionsQuery.error ?? versionsQuery.error ?? cropsQuery.error;

  const hasDraft = versions.some((v) => v.status === "draft");

  function closeAction() {
    setAction(null);
    setActionError(null);
  }

  return (
    <StandaloneShell>
      <PageHeader
        title={definition ? definition.name : "Grade Definition"}
        breadcrumbs={
          <Breadcrumbs
            items={[
              { label: "Home", href: "/farms" },
              { label: "Grade Definitions", href: "/grade-definitions" },
              { label: definition?.name ?? "Grade Definition" },
            ]}
          />
        }
      />

      {isLoading && <LoadingSkeleton rows={4} label="Loading grade definition" />}
      {loadError && (
        <ErrorState
          error={loadError}
          onRetry={() => {
            definitionsQuery.refetch();
            versionsQuery.refetch();
            cropsQuery.refetch();
          }}
        />
      )}
      {!isLoading && !loadError && !definition && (
        <ErrorState error={new AppError("not_found", "This grade definition could not be found.")} />
      )}

      {!isLoading && !loadError && definition && (
        <div className="flex flex-col gap-6">
          <dl className="grid grid-cols-1 gap-4 rounded-xl border border-border-subtle bg-surface p-4 sm:grid-cols-2">
            <div>
              <dt className="text-xs font-medium uppercase text-ink-muted">Code</dt>
              <dd className="text-sm text-ink">{definition.code}</dd>
            </div>
            <div>
              <dt className="text-xs font-medium uppercase text-ink-muted">Crop</dt>
              <dd className="text-sm text-ink">{crop ? `${crop.common_name} (${crop.code})` : "—"}</dd>
            </div>
            <div>
              <dt className="text-xs font-medium uppercase text-ink-muted">Variety</dt>
              <dd className="text-sm text-ink">
                {definition.variety_id ? (variety ? `${variety.name} (${variety.code})` : "—") : "Any variety"}
              </dd>
            </div>
            <div>
              <dt className="text-xs font-medium uppercase text-ink-muted">Description</dt>
              <dd className="text-sm text-ink">{definition.description ?? "—"}</dd>
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

            {action?.kind === "create" && (
              <div className="mb-4">
                <GradeDefinitionVersionForm
                  isSubmitting={createVersion.isPending}
                  serverError={actionError}
                  onCancel={closeAction}
                  onSubmit={(payload) => {
                    setActionError(null);
                    createVersion.mutate(payload, {
                      onSuccess: closeAction,
                      onError: (error) => setActionError(errorMessage(error)),
                    });
                  }}
                />
              </div>
            )}

            {action?.kind === "activate" && (
              <div className="mb-4">
                <EffectiveTimeActionPanel
                  heading={`Activate version ${action.version.version_number}`}
                  confirmLabel="Activate version"
                  isPending={activateVersion.isPending}
                  error={actionError}
                  onCancel={closeAction}
                  summary={
                    <>
                      <div>
                        <dt className="text-xs font-medium uppercase text-ink-muted">Grade definition</dt>
                        <dd className="text-sm text-ink">{definition.name}</dd>
                      </div>
                      <div>
                        <dt className="text-xs font-medium uppercase text-ink-muted">Version</dt>
                        <dd className="text-sm text-ink">v{action.version.version_number}</dd>
                      </div>
                      <div className="sm:col-span-2">
                        <dt className="text-xs font-medium uppercase text-ink-muted">Spec notes</dt>
                        <dd className="text-sm text-ink">{action.version.spec_notes ?? "—"}</dd>
                      </div>
                    </>
                  }
                  onConfirm={(effectiveTimeIso) => {
                    setActionError(null);
                    activateVersion.mutate(
                      {
                        versionId: action.version.id,
                        payload: { client_command_id: crypto.randomUUID(), effective_time: effectiveTimeIso },
                      },
                      { onSuccess: closeAction, onError: (error) => setActionError(errorMessage(error)) },
                    );
                  }}
                />
              </div>
            )}

            {action?.kind === "retire" && (
              <div className="mb-4">
                <EffectiveTimeActionPanel
                  heading={`Retire version ${action.version.version_number}`}
                  confirmLabel="Retire version"
                  confirmVariant="danger"
                  isPending={retireVersion.isPending}
                  error={actionError}
                  onCancel={closeAction}
                  summary={
                    <>
                      <div>
                        <dt className="text-xs font-medium uppercase text-ink-muted">Grade definition</dt>
                        <dd className="text-sm text-ink">{definition.name}</dd>
                      </div>
                      <div>
                        <dt className="text-xs font-medium uppercase text-ink-muted">Version</dt>
                        <dd className="text-sm text-ink">v{action.version.version_number}</dd>
                      </div>
                    </>
                  }
                  onConfirm={(effectiveTimeIso) => {
                    setActionError(null);
                    retireVersion.mutate(
                      {
                        versionId: action.version.id,
                        payload: { client_command_id: crypto.randomUUID(), effective_time: effectiveTimeIso },
                      },
                      { onSuccess: closeAction, onError: (error) => setActionError(errorMessage(error)) },
                    );
                  }}
                />
              </div>
            )}

            {action === null && versions.length === 0 && (
              <EmptyState
                title="No versions yet"
                description="Create the first draft version to define this grade's spec notes, then activate it explicitly."
                action={
                  <Button variant="primary" onClick={() => setAction({ kind: "create" })}>
                    Create draft version
                  </Button>
                }
              />
            )}

            {action === null && versions.length > 0 && (
              <>
                <div className="overflow-x-auto rounded-xl border border-border-subtle bg-surface">
                  <table className="w-full text-left text-sm">
                    <thead className="border-b border-border-subtle bg-surface-subtle text-xs uppercase text-ink-muted">
                      <tr>
                        <th className="px-4 py-2 font-medium">Version</th>
                        <th className="px-4 py-2 font-medium">Status</th>
                        <th className="px-4 py-2 font-medium">Effective from</th>
                        <th className="px-4 py-2 font-medium">Effective until</th>
                        <th className="px-4 py-2 font-medium">Spec notes</th>
                        <th className="px-4 py-2 font-medium" />
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-border-subtle">
                      {versions.map((version) => (
                        <tr key={version.id} className="hover:bg-surface-subtle">
                          <td className="px-4 py-2 font-medium text-ink">v{version.version_number}</td>
                          <td className="px-4 py-2">
                            <StatusBadge
                              label={version.status.charAt(0).toUpperCase() + version.status.slice(1)}
                              tone={versionTone(version.status)}
                            />
                          </td>
                          <td className="px-4 py-2 text-ink-muted">
                            {version.effective_from ? new Date(version.effective_from).toLocaleString() : "—"}
                          </td>
                          <td className="px-4 py-2 text-ink-muted">
                            {version.effective_until ? new Date(version.effective_until).toLocaleString() : "—"}
                          </td>
                          <td className="px-4 py-2 text-ink-muted">{version.spec_notes ?? "—"}</td>
                          <td className="px-4 py-2">
                            <div className="flex gap-2">
                              {version.status === "draft" && (
                                <Button variant="primary" onClick={() => setAction({ kind: "activate", version })}>
                                  Review &amp; activate
                                </Button>
                              )}
                              {version.status === "active" && (
                                <Button variant="secondary" onClick={() => setAction({ kind: "retire", version })}>
                                  Retire
                                </Button>
                              )}
                            </div>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>

                {!hasDraft && (
                  <div className="mt-4">
                    <Button variant="secondary" onClick={() => setAction({ kind: "create" })}>
                      Create new draft version
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
