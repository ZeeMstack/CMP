"use client";

import { PlusCircle } from "lucide-react";
import Link from "next/link";

import { Breadcrumbs } from "@/components/Breadcrumbs";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { LoadingSkeleton } from "@/components/LoadingSkeleton";
import { PageHeader } from "@/components/PageHeader";
import { StandaloneShell } from "@/components/StandaloneShell";
import { StatusBadge, type StatusTone } from "@/components/StatusBadge";
import { Button } from "@/components/ui/Button";
import {
  tableBodyDividerClass,
  tableHeadRowClass,
  tableRowHoverClass,
  tableTdClass,
  tableThClass,
  tableWrapperClass,
} from "@/components/ui/table";
import { useCrops, useProductionSystems, useWorkflows } from "@/lib/query/hooks";

/** PILOT-SETUP-001B6 / B6A: this list intentionally stays a simple Workflow
 * master-data list (`GET /workflows`) -- it never decorates every row with
 * its version state, which would require an extra per-row request (N+1).
 * "View" opens the Workflow's own detail page, which now fetches and
 * displays that Workflow's full version catalog (`GET /workflows/{id}/
 * versions`, added in B6A) and offers "Resume Draft"/"View Published
 * Version"/"View Retired Version" per row there instead. */
export default function WorkflowsPage() {
  const workflowsQuery = useWorkflows();
  const cropsQuery = useCrops();
  const productionSystemsQuery = useProductionSystems();

  const workflows = workflowsQuery.data ?? [];
  const crops = cropsQuery.data ?? [];
  const productionSystems = productionSystemsQuery.data ?? [];

  const isLoading = workflowsQuery.isLoading || cropsQuery.isLoading || productionSystemsQuery.isLoading;
  const loadError = workflowsQuery.error ?? cropsQuery.error ?? productionSystemsQuery.error;

  return (
    <StandaloneShell>
      <PageHeader
        title="Workflows"
        breadcrumbs={<Breadcrumbs items={[{ label: "Home", href: "/farms" }, { label: "Workflows" }]} />}
        actions={
          <Link href="/workflows/new">
            <Button variant="primary">
              <PlusCircle aria-hidden="true" className="h-4 w-4" />
              New workflow
            </Button>
          </Link>
        }
      />
      <p className="-mt-3 mb-6 text-xs text-wl-text-secondary">
        Tenant-wide crop workflow catalog: stage/transition configuration a Crop Batch runs against once published.
      </p>

      {isLoading && <LoadingSkeleton rows={4} label="Loading workflows" />}
      {loadError && (
        <ErrorState
          error={loadError}
          onRetry={() => {
            workflowsQuery.refetch();
            cropsQuery.refetch();
            productionSystemsQuery.refetch();
          }}
        />
      )}

      {!isLoading && !loadError && workflows.length === 0 && (
        <EmptyState
          title="No workflows yet"
          description="Create the first workflow once at least one crop and production system exist."
        />
      )}

      {!isLoading && !loadError && workflows.length > 0 && (
        <div className={tableWrapperClass}>
          <table className="w-full text-left text-sm">
            <thead>
              <tr className={tableHeadRowClass}>
                <th className={tableThClass}>Code</th>
                <th className={tableThClass}>Name</th>
                <th className={tableThClass}>Crop</th>
                <th className={tableThClass}>Production system</th>
                <th className={tableThClass}>Status</th>
                <th className={tableThClass} />
              </tr>
            </thead>
            <tbody className={tableBodyDividerClass}>
              {workflows.map((workflow) => {
                const crop = crops.find((c) => c.id === workflow.crop_id);
                const productionSystem = productionSystems.find((p) => p.id === workflow.production_system_id);
                const tone: StatusTone = workflow.status === "active" ? "active" : "closed";
                return (
                  <tr key={workflow.id} className={tableRowHoverClass}>
                    <td className={`${tableTdClass} font-medium text-wl-text`}>{workflow.code}</td>
                    <td className={`${tableTdClass} text-wl-text`}>{workflow.name}</td>
                    <td className={`${tableTdClass} text-wl-text-secondary`}>{crop ? crop.common_name : "—"}</td>
                    <td className={`${tableTdClass} text-wl-text-secondary`}>{productionSystem ? productionSystem.name : "—"}</td>
                    <td className={tableTdClass}>
                      <StatusBadge label={workflow.status === "active" ? "Active" : "Inactive"} tone={tone} />
                    </td>
                    <td className={tableTdClass}>
                      <Link href={`/workflows/${workflow.id}`} className="text-sm font-medium text-wl-brand hover:underline">
                        View
                      </Link>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </StandaloneShell>
  );
}
