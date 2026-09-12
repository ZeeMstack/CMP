"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";

import { Breadcrumbs } from "@/components/Breadcrumbs";
import { ErrorState } from "@/components/ErrorState";
import { LoadingSkeleton } from "@/components/LoadingSkeleton";
import { PageHeader } from "@/components/PageHeader";
import { StatusBadge } from "@/components/StatusBadge";
import { Button } from "@/components/ui/Button";
import { AppError } from "@/lib/errors/adapter";
import { formatPlanDate } from "@/lib/format/planDate";
import { formatQuantity } from "@/lib/format/planQuantity";
import { useCancelSeedingProgramLine, useSeedingProgramLine } from "@/lib/query/hooks";

export default function SeedingProgramLineDetailPage() {
  const { farmId, lineId } = useParams<{ farmId: string; lineId: string }>();
  const lineQuery = useSeedingProgramLine(farmId, lineId);
  const [actionError, setActionError] = useState<string | null>(null);
  // Hooks must run unconditionally on every render -- the requirement id
  // needed for cache invalidation is only known once `line` has loaded, so
  // this falls back to an empty string until then (harmless: the mutation
  // itself is never invoked before the line, and therefore this id, exists).
  const cancelMutation = useCancelSeedingProgramLine(
    farmId, lineQuery.data?.production_requirement_id ?? "", lineId,
  );

  if (lineQuery.isLoading) {
    return <LoadingSkeleton rows={4} label="Loading plan line" />;
  }
  if (lineQuery.error) {
    return <ErrorState error={lineQuery.error} onRetry={() => lineQuery.refetch()} />;
  }
  const line = lineQuery.data;
  if (!line) return null;

  const sowNowParams = new URLSearchParams({ seeding_program_line_id: line.id, crop_id: line.crop.id });
  if (line.variety) sowNowParams.set("variety_id", line.variety.id);

  return (
    <div>
      <PageHeader
        title={`Plan line — ${formatPlanDate(line.planned_sow_date)}`}
        breadcrumbs={
          <Breadcrumbs
            items={[
              { label: "Home", href: `/farms/${farmId}` },
              { label: "Planning", href: `/farms/${farmId}/planning` },
              {
                label: line.requirement_code,
                href: `/farms/${farmId}/planning/requirements/${line.production_requirement_id}`,
              },
              { label: "Plan line" },
            ]}
          />
        }
        actions={
          <div className="flex flex-wrap items-center gap-2">
            {line.status !== "cancelled" && (
              <Link
                href={`/farms/${farmId}/nursery/sowings/new?${sowNowParams.toString()}`}
                className="flex min-h-11 items-center rounded-md bg-wl-brand px-3 text-sm font-medium text-wl-text-on-brand hover:bg-wl-brand-hover focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-wl-focus"
              >
                Sow now
              </Link>
            )}
            {line.status !== "cancelled" && (
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
                {cancelMutation.isPending ? "Cancelling…" : "Cancel plan line"}
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

      <div className="mb-6 grid grid-cols-2 gap-4 rounded-lg border border-wl-border p-4 sm:grid-cols-4">
        <div>
          <p className="text-xs text-wl-text-tertiary">Crop</p>
          <p className="text-sm font-medium text-wl-text">
            {line.crop.common_name}
            {line.variety ? ` — ${line.variety.name}` : ""}
          </p>
        </div>
        <div>
          <p className="text-xs text-wl-text-tertiary">Status</p>
          {/* PILOT-UX-003: `linked_sowing_count` is a record count, never
              proof the planned quantity was fully sown -- see
              `SeedingProgramTable.tsx`'s identical `lineStatusLabel`. */}
          <StatusBadge
            label={line.status === "cancelled" ? "Cancelled" : line.linked_sowing_count > 0 ? "Sowing recorded" : "Planned"}
            tone={line.status === "cancelled" ? "neutral" : line.linked_sowing_count > 0 ? "closed" : "active"}
          />
        </div>
        <div>
          <p className="text-xs text-wl-text-tertiary">Planned sowing</p>
          <p className="text-sm font-medium text-wl-text">
            {formatQuantity(line.planned_quantity, line.planned_quantity_uom.code)}
          </p>
        </div>
        <div>
          <p className="text-xs text-wl-text-tertiary">Expected coverage</p>
          <p className="text-sm font-medium text-wl-text">
            {formatQuantity(line.expected_coverage_quantity, line.expected_coverage_uom.code)}
          </p>
        </div>
        {line.notes && (
          <div className="col-span-2 sm:col-span-4">
            <p className="text-xs text-wl-text-tertiary">Notes</p>
            <p className="text-sm text-wl-text">{line.notes}</p>
          </div>
        )}
      </div>

      <h2 className="mb-3 font-serif text-lg font-semibold text-wl-text">Actual sowings</h2>
      {line.linked_sowings.length === 0 && (
        <p className="text-sm text-wl-text-secondary">
          Not sown yet — planned biological execution has not begun. Actual sowing never implies a harvest
          quantity.
        </p>
      )}
      {line.linked_sowings.length > 0 && (
        <ul className="divide-y divide-wl-border rounded-lg border border-wl-border">
          {line.linked_sowings.map((sowing) => (
            <li key={sowing.id} className="flex items-center justify-between px-3 py-2 text-sm">
              <Link
                href={`/farms/${farmId}/crop-batches/${sowing.batch_id}?tab=sowing`}
                className="font-medium text-wl-text hover:underline"
              >
                {sowing.batch_code}
              </Link>
              <span className="text-wl-text-secondary">{sowing.total_seeds_sown} seeds sown</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
