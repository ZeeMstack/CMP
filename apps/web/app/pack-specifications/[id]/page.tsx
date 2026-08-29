"use client";

import { useParams } from "next/navigation";
import { useState } from "react";

import { Breadcrumbs } from "@/components/Breadcrumbs";
import { EffectiveTimeActionPanel } from "@/components/EffectiveTimeActionPanel";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { LoadingSkeleton } from "@/components/LoadingSkeleton";
import { PackSpecificationVersionForm } from "@/components/pack-specifications/PackSpecificationVersionForm";
import { PageHeader } from "@/components/PageHeader";
import { StandaloneShell } from "@/components/StandaloneShell";
import { StatusBadge, type StatusTone } from "@/components/StatusBadge";
import { Button } from "@/components/ui/Button";
import type { PackSpecificationVersionRead } from "@/lib/api/client";
import { AppError } from "@/lib/errors/adapter";
import {
  useActivatePackSpecificationVersion,
  useAllPackSpecifications,
  useCreatePackSpecificationVersion,
  useCrops,
  usePackagingUnits,
  usePackSpecificationVersions,
  useRetirePackSpecificationVersion,
  useSelectableGradeDefinitionVersions,
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

function formatWeight(nominalNetWeightKg: string | null): string {
  return nominalNetWeightKg == null ? "—" : `${nominalNetWeightKg} kg`;
}

type ActionState =
  | { kind: "create" }
  | { kind: "activate"; version: PackSpecificationVersionRead }
  | { kind: "retire"; version: PackSpecificationVersionRead }
  | null;

/** PILOT-SETUP-001B7: mirrors `GradeDefinitionDetailPage` exactly -- the
 * Pack Specification's own identity is found in the already-cached
 * tenant-wide list (shared with the Packing operator picker), the version
 * catalog lists every version regardless of lifecycle status, and every
 * lifecycle action requires an explicit confirm. The packaging-unit picker
 * for a NEW draft version is filtered to ACTIVE units only (a retired unit
 * is never offered for a new reference); the grade-version picker excludes
 * DRAFT versions (never a valid reference, backend-enforced). */
export default function PackSpecificationDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [action, setAction] = useState<ActionState>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const specsQuery = useAllPackSpecifications();
  const versionsQuery = usePackSpecificationVersions(id);
  const cropsQuery = useCrops();
  const packagingUnitsQuery = usePackagingUnits();
  const { versions: gradeVersions, isLoading: gradeVersionsLoading } = useSelectableGradeDefinitionVersions();
  const createVersion = useCreatePackSpecificationVersion(id);
  const activateVersion = useActivatePackSpecificationVersion(id);
  const retireVersion = useRetirePackSpecificationVersion(id);

  const spec = specsQuery.data?.find((s) => s.id === id);
  const versions = versionsQuery.data ?? [];
  const crop = cropsQuery.data?.find((c) => c.id === spec?.crop_id);
  const varietiesQuery = useVarieties(spec?.crop_id);
  const variety = varietiesQuery.data?.find((v) => v.id === spec?.variety_id);
  const activePackagingUnits = (packagingUnitsQuery.data ?? []).filter((u) => u.status === "active");
  const packagingUnitLabel = (packagingUnitId: string) => {
    const unit = packagingUnitsQuery.data?.find((u) => u.id === packagingUnitId);
    return unit ? `${unit.name} (${unit.code})` : "—";
  };
  const gradeVersionLabel = (gradeVersionId: string | null) =>
    gradeVersionId ? gradeVersions.find((v) => v.id === gradeVersionId)?.label ?? "—" : "None";

  const isLoading =
    specsQuery.isLoading || versionsQuery.isLoading || cropsQuery.isLoading || packagingUnitsQuery.isLoading;
  const loadError = specsQuery.error ?? versionsQuery.error ?? cropsQuery.error ?? packagingUnitsQuery.error;

  const hasDraft = versions.some((v) => v.status === "draft");

  function closeAction() {
    setAction(null);
    setActionError(null);
  }

  return (
    <StandaloneShell>
      <PageHeader
        title={spec ? spec.name : "Pack Specification"}
        breadcrumbs={
          <Breadcrumbs
            items={[
              { label: "Home", href: "/farms" },
              { label: "Pack Specifications", href: "/pack-specifications" },
              { label: spec?.name ?? "Pack Specification" },
            ]}
          />
        }
      />

      {isLoading && <LoadingSkeleton rows={4} label="Loading pack specification" />}
      {loadError && (
        <ErrorState
          error={loadError}
          onRetry={() => {
            specsQuery.refetch();
            versionsQuery.refetch();
            cropsQuery.refetch();
            packagingUnitsQuery.refetch();
          }}
        />
      )}
      {!isLoading && !loadError && !spec && (
        <ErrorState error={new AppError("not_found", "This pack specification could not be found.")} />
      )}

      {!isLoading && !loadError && spec && (
        <div className="flex flex-col gap-6">
          <dl className="grid grid-cols-1 gap-4 rounded-xl border border-border-subtle bg-surface p-4 sm:grid-cols-2">
            <div>
              <dt className="text-xs font-medium uppercase text-ink-muted">Code</dt>
              <dd className="text-sm text-ink">{spec.code}</dd>
            </div>
            <div>
              <dt className="text-xs font-medium uppercase text-ink-muted">Crop</dt>
              <dd className="text-sm text-ink">{crop ? `${crop.common_name} (${crop.code})` : "—"}</dd>
            </div>
            <div>
              <dt className="text-xs font-medium uppercase text-ink-muted">Variety</dt>
              <dd className="text-sm text-ink">
                {spec.variety_id ? (variety ? `${variety.name} (${variety.code})` : "—") : "Any variety"}
              </dd>
            </div>
            <div>
              <dt className="text-xs font-medium uppercase text-ink-muted">Customer reference</dt>
              <dd className="text-sm text-ink">{spec.customer_reference ?? "—"}</dd>
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
                <PackSpecificationVersionForm
                  packagingUnits={activePackagingUnits}
                  gradeVersions={gradeVersionsLoading ? [] : gradeVersions}
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
                        <dt className="text-xs font-medium uppercase text-ink-muted">Pack specification</dt>
                        <dd className="text-sm text-ink">{spec.name}</dd>
                      </div>
                      <div>
                        <dt className="text-xs font-medium uppercase text-ink-muted">Version</dt>
                        <dd className="text-sm text-ink">v{action.version.version_number}</dd>
                      </div>
                      <div>
                        <dt className="text-xs font-medium uppercase text-ink-muted">Packaging unit</dt>
                        <dd className="text-sm text-ink">{packagingUnitLabel(action.version.packaging_unit_id)}</dd>
                      </div>
                      <div>
                        <dt className="text-xs font-medium uppercase text-ink-muted">Grade</dt>
                        <dd className="text-sm text-ink">{gradeVersionLabel(action.version.grade_definition_version_id)}</dd>
                      </div>
                      <div>
                        <dt className="text-xs font-medium uppercase text-ink-muted">Nominal net weight</dt>
                        <dd className="text-sm text-ink">{formatWeight(action.version.nominal_net_weight_kg)}</dd>
                      </div>
                      <div>
                        <dt className="text-xs font-medium uppercase text-ink-muted">Whole units per pack</dt>
                        <dd className="text-sm text-ink">{action.version.whole_units_per_pack ?? "—"}</dd>
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
                        <dt className="text-xs font-medium uppercase text-ink-muted">Pack specification</dt>
                        <dd className="text-sm text-ink">{spec.name}</dd>
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
              <>
                <EmptyState
                  title="No versions yet"
                  description="Create the first draft version with a packaging unit and pack size, then activate it explicitly."
                  action={
                    <Button
                      variant="primary"
                      onClick={() => setAction({ kind: "create" })}
                      disabled={activePackagingUnits.length === 0}
                    >
                      Create draft version
                    </Button>
                  }
                />
                {activePackagingUnits.length === 0 && (
                  <p className="mt-3 text-xs text-ink-muted">
                    Register at least one active Packaging Unit before creating a Pack Specification Version.
                  </p>
                )}
              </>
            )}

            {action === null && versions.length > 0 && (
              <>
                <div className="overflow-x-auto rounded-xl border border-border-subtle bg-surface">
                  <table className="w-full text-left text-sm">
                    <thead className="border-b border-border-subtle bg-surface-subtle text-xs uppercase text-ink-muted">
                      <tr>
                        <th className="px-4 py-2 font-medium">Version</th>
                        <th className="px-4 py-2 font-medium">Status</th>
                        <th className="px-4 py-2 font-medium">Packaging unit</th>
                        <th className="px-4 py-2 font-medium">Weight</th>
                        <th className="px-4 py-2 font-medium">Units</th>
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
                          <td className="px-4 py-2 text-ink-muted">{packagingUnitLabel(version.packaging_unit_id)}</td>
                          <td className="px-4 py-2 text-ink-muted">{formatWeight(version.nominal_net_weight_kg)}</td>
                          <td className="px-4 py-2 text-ink-muted">{version.whole_units_per_pack ?? "—"}</td>
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
                    <Button
                      variant="secondary"
                      onClick={() => setAction({ kind: "create" })}
                      disabled={activePackagingUnits.length === 0}
                    >
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
