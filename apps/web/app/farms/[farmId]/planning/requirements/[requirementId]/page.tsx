"use client";

import { PlusCircle } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";

import { Breadcrumbs } from "@/components/Breadcrumbs";
import { ErrorState } from "@/components/ErrorState";
import { LoadingSkeleton } from "@/components/LoadingSkeleton";
import { PageHeader } from "@/components/PageHeader";
import { EmptyState } from "@/components/EmptyState";
import { RequirementContributingBatchesPanel } from "@/components/planning/RequirementContributingBatchesPanel";
import { RequirementUpdateForm } from "@/components/planning/RequirementUpdateForm";
import { SeedingProgramTable } from "@/components/planning/SeedingProgramTable";
import { StatusBadge } from "@/components/StatusBadge";
import { Button } from "@/components/ui/Button";
import { AppError } from "@/lib/errors/adapter";
import { COVERAGE_STATUS_LABEL, deriveCoverageStatus } from "@/lib/format/forecastCoverage";
import { formatPlanDate } from "@/lib/format/planDate";
import { formatQuantity } from "@/lib/format/planQuantity";
import {
  useCancelProductionRequirement,
  useCloseProductionRequirement,
  useProductionRequirement,
  useRequirementHarvestOutlook,
  useSeedingProgramLinesForRequirement,
  useUpdateProductionRequirement,
} from "@/lib/query/hooks";

export default function ProductionRequirementDetailPage() {
  const { farmId, requirementId } = useParams<{ farmId: string; requirementId: string }>();
  const requirementQuery = useProductionRequirement(farmId, requirementId);
  const linesQuery = useSeedingProgramLinesForRequirement(farmId, requirementId);
  const outlookQuery = useRequirementHarvestOutlook(farmId, requirementId);

  const updateMutation = useUpdateProductionRequirement(farmId, requirementId);
  const closeMutation = useCloseProductionRequirement(farmId, requirementId);
  const cancelMutation = useCancelProductionRequirement(farmId, requirementId);

  const [editing, setEditing] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  if (requirementQuery.isLoading) {
    return <LoadingSkeleton rows={4} label="Loading production requirement" />;
  }
  if (requirementQuery.error) {
    return <ErrorState error={requirementQuery.error} onRetry={() => requirementQuery.refetch()} />;
  }
  const requirement = requirementQuery.data;
  if (!requirement) return null;

  const fulfillment = requirement.fulfillment;
  const isOpen = requirement.status === "open";

  return (
    <div>
      <PageHeader
        title={requirement.code}
        breadcrumbs={
          <Breadcrumbs
            items={[
              { label: "Home", href: `/farms/${farmId}` },
              { label: "Planning", href: `/farms/${farmId}/planning` },
              { label: requirement.code },
            ]}
          />
        }
        actions={
          <div className="flex flex-wrap items-center gap-2">
            {isOpen && !editing && (
              <Button variant="secondary" onClick={() => setEditing(true)}>
                Edit
              </Button>
            )}
            {isOpen && (
              <Button
                variant="secondary"
                disabled={closeMutation.isPending}
                onClick={() => {
                  setActionError(null);
                  closeMutation.mutate(
                    { client_command_id: crypto.randomUUID() },
                    {
                      onError: (error) =>
                        setActionError(error instanceof AppError ? error.message : "Something went wrong."),
                    },
                  );
                }}
              >
                {closeMutation.isPending ? "Closing…" : "Close"}
              </Button>
            )}
            {requirement.status !== "cancelled" && (
              <Button
                variant="danger"
                disabled={cancelMutation.isPending}
                onClick={() => {
                  setActionError(null);
                  cancelMutation.mutate(
                    { client_command_id: crypto.randomUUID() },
                    {
                      onError: (error) =>
                        setActionError(error instanceof AppError ? error.message : "Something went wrong."),
                    },
                  );
                }}
              >
                {cancelMutation.isPending ? "Cancelling…" : "Cancel"}
              </Button>
            )}
          </div>
        }
      />

      {actionError && (
        <p role="alert" className="mb-4 text-sm text-red-700">
          {actionError}
        </p>
      )}

      {editing ? (
        <RequirementUpdateForm
          requirement={requirement}
          isSubmitting={updateMutation.isPending}
          serverError={updateMutation.error instanceof AppError ? updateMutation.error.message : null}
          onCancel={() => setEditing(false)}
          onSubmit={(payload) => {
            updateMutation.mutate(payload, { onSuccess: () => setEditing(false) });
          }}
        />
      ) : (
        <div className="mb-6 grid grid-cols-2 gap-4 rounded-lg border border-wl-border p-4 sm:grid-cols-4">
          <div>
            <p className="text-xs text-wl-text-tertiary">Crop</p>
            <p className="text-sm font-medium text-wl-text">
              {requirement.crop.common_name}
              {requirement.variety ? ` — ${requirement.variety.name}` : ""}
            </p>
          </div>
          <div>
            <p className="text-xs text-wl-text-tertiary">Required by</p>
            <p className="text-sm font-medium text-wl-text">{formatPlanDate(requirement.required_by_date)}</p>
          </div>
          <div>
            <p className="text-xs text-wl-text-tertiary">Status</p>
            <StatusBadge
              label={requirement.status[0].toUpperCase() + requirement.status.slice(1)}
              tone={requirement.status === "open" ? "active" : requirement.status === "closed" ? "closed" : "neutral"}
            />
          </div>
          <div>
            <p className="text-xs text-wl-text-tertiary">Reference</p>
            <p className="text-sm font-medium text-wl-text">{requirement.reference ?? "—"}</p>
          </div>

          <div>
            <p className="text-xs text-wl-text-tertiary">Demand</p>
            <p className="text-sm font-medium text-wl-text">
              {formatQuantity(requirement.required_quantity, requirement.uom.code)}
            </p>
          </div>
          <div>
            <p className="text-xs text-wl-text-tertiary">Planned coverage</p>
            <p className="text-sm font-medium text-wl-text">
              {formatQuantity(fulfillment.planned_coverage_quantity, requirement.uom.code)}
            </p>
          </div>
          <div>
            <p className="text-xs text-wl-text-tertiary">{fulfillment.is_overplanned ? "Overplanned" : "Gap"}</p>
            <p className="text-sm font-medium text-wl-text">
              {fulfillment.is_overplanned
                ? `+${formatQuantity(fulfillment.overplanned_quantity, requirement.uom.code)}`
                : formatQuantity(fulfillment.gap_quantity, requirement.uom.code)}
            </p>
          </div>
          <div>
            <p className="text-xs text-wl-text-tertiary">Actual sowings</p>
            <p className="text-sm font-medium text-wl-text">
              {fulfillment.actual_sowings_count} / {fulfillment.planned_lines_count} planned
            </p>
          </div>

          {requirement.notes && (
            <div className="col-span-2 sm:col-span-4">
              <p className="text-xs text-wl-text-tertiary">Notes</p>
              <p className="text-sm text-wl-text">{requirement.notes}</p>
            </div>
          )}
        </div>
      )}

      <div className="mb-6">
        <h2 className="mb-3 font-serif text-lg font-semibold text-wl-text">Harvest Outlook</h2>
        {outlookQuery.isLoading && <LoadingSkeleton rows={2} label="Loading harvest outlook" />}
        {outlookQuery.error && <ErrorState error={outlookQuery.error} onRetry={() => outlookQuery.refetch()} />}
        {outlookQuery.data && (
          <>
            <div className="grid grid-cols-2 gap-4 rounded-lg border border-wl-border p-4 sm:grid-cols-5">
              <div>
                <p className="text-xs text-wl-text-tertiary">Contributing batches</p>
                <p className="text-sm font-medium text-wl-text">{outlookQuery.data.contributing_batch_count}</p>
              </div>
              <div>
                <p className="text-xs text-wl-text-tertiary">With current forecast</p>
                <p className="text-sm font-medium text-wl-text">{outlookQuery.data.batches_with_current_forecast_count}</p>
              </div>
              <div>
                <p className="text-xs text-wl-text-tertiary">Forecast (expected)</p>
                <p className="text-sm font-medium text-wl-text">
                  {outlookQuery.data.forecast_comparable && outlookQuery.data.forecast_expected_quantity !== null
                    ? formatQuantity(outlookQuery.data.forecast_expected_quantity, requirement.uom.code)
                    : "Not comparable"}
                </p>
              </div>
              <div>
                <p className="text-xs text-wl-text-tertiary">Actual harvested</p>
                <p className="text-sm font-medium text-wl-text">
                  {outlookQuery.data.actual_harvested_comparable && outlookQuery.data.actual_harvested_quantity !== null
                    ? formatQuantity(outlookQuery.data.actual_harvested_quantity, requirement.uom.code)
                    : `Not comparable (${outlookQuery.data.actual_harvested_weight_kg} kg)`}
                </p>
              </div>
              <div>
                <p className="text-xs text-wl-text-tertiary">Outlook</p>
                <StatusBadge
                  label={COVERAGE_STATUS_LABEL[deriveCoverageStatus(outlookQuery.data)]}
                  tone={
                    deriveCoverageStatus(outlookQuery.data) === "SHORT"
                      ? "attention"
                      : deriveCoverageStatus(outlookQuery.data) === "COVERED"
                        ? "active"
                        : "neutral"
                  }
                />
              </div>
            </div>
            <p className="mt-2 text-xs text-wl-text-secondary">
              Forecast and Actual are read from each contributing Batch&apos;s own Harvest Forecast -- this is a
              read-only outlook, never a second demand ledger. See the contributing Batches below.
            </p>
          </>
        )}
      </div>

      <div className="mb-6">
        <h2 className="mb-3 font-serif text-lg font-semibold text-wl-text">Contributing Batches</h2>
        <RequirementContributingBatchesPanel farmId={farmId} requirementId={requirementId} />
      </div>

      <div className="mb-3 flex items-center justify-between">
        <h2 className="font-serif text-lg font-semibold text-wl-text">Seeding Program</h2>
        {isOpen && (
          <Link
            href={`/farms/${farmId}/planning/requirements/${requirementId}/seeding-program-lines/new`}
            className="flex min-h-9 items-center gap-1.5 rounded-md bg-wl-brand px-3 text-sm font-medium text-wl-text-on-brand hover:bg-wl-brand-hover focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-wl-focus"
          >
            <PlusCircle aria-hidden="true" className="h-4 w-4" />
            Add plan line
          </Link>
        )}
      </div>

      {linesQuery.isLoading && <LoadingSkeleton rows={3} label="Loading plan lines" />}
      {linesQuery.error && <ErrorState error={linesQuery.error} onRetry={() => linesQuery.refetch()} />}
      {linesQuery.data && linesQuery.data.length === 0 && (
        <EmptyState
          title="No planned sowings yet."
          description="Add a plan line to schedule a sowing intended to cover part of this requirement's demand."
        />
      )}
      {linesQuery.data && linesQuery.data.length > 0 && (
        <SeedingProgramTable lines={linesQuery.data} farmId={farmId} />
      )}
    </div>
  );
}
