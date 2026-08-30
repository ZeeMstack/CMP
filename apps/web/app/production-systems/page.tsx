"use client";

import { PlusCircle } from "lucide-react";
import { useState } from "react";

import { Breadcrumbs } from "@/components/Breadcrumbs";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { LoadingSkeleton } from "@/components/LoadingSkeleton";
import { PageHeader } from "@/components/PageHeader";
import { ProductionSystemForm } from "@/components/production-systems/ProductionSystemForm";
import { StandaloneShell } from "@/components/StandaloneShell";
import { StatusBadge, type StatusTone } from "@/components/StatusBadge";
import { Button } from "@/components/ui/Button";
import type { ProductionSystemCreate } from "@/lib/api/client";
import { AppError } from "@/lib/errors/adapter";
import { useCreateProductionSystem, useProductionSystems } from "@/lib/query/hooks";

function errorMessage(error: unknown): string {
  return error instanceof AppError ? error.message : "Something went wrong. Please try again.";
}

/** PILOT-SETUP-001B6: tenant-level Production System master data -- the
 * growing-system/workflow master a Workflow references, not fertigation
 * recipes or climate/hardware configuration (no such fields exist on this
 * resource). */
export default function ProductionSystemsPage() {
  const [creating, setCreating] = useState(false);
  const [serverError, setServerError] = useState<string | null>(null);

  const query = useProductionSystems();
  const createMutation = useCreateProductionSystem();
  const systems = query.data ?? [];

  function handleSubmit(payload: ProductionSystemCreate) {
    setServerError(null);
    createMutation.mutate(payload, {
      onSuccess: () => setCreating(false),
      onError: (error) => setServerError(errorMessage(error)),
    });
  }

  return (
    <StandaloneShell>
      <PageHeader
        title="Production Systems"
        breadcrumbs={
          <Breadcrumbs items={[{ label: "Home", href: "/farms" }, { label: "Production Systems" }]} />
        }
        actions={
          !creating && (
            <Button variant="primary" onClick={() => setCreating(true)}>
              <PlusCircle aria-hidden="true" className="h-4 w-4" />
              New production system
            </Button>
          )
        }
      />
      <p className="-mt-3 mb-6 text-xs text-ink-muted">
        Tenant-wide growing-system catalog a Workflow configures against (e.g. NFT, DWC, media bags).
      </p>

      {creating && (
        <ProductionSystemForm
          isSubmitting={createMutation.isPending}
          serverError={serverError}
          onCancel={() => {
            setCreating(false);
            setServerError(null);
          }}
          onSubmit={handleSubmit}
        />
      )}

      {!creating && (
        <>
          {query.isLoading && <LoadingSkeleton rows={4} label="Loading production systems" />}
          {query.error && <ErrorState error={query.error} onRetry={() => query.refetch()} />}
          {!query.isLoading && !query.error && systems.length === 0 && (
            <EmptyState
              title="No production systems yet"
              description="Register the first production system before configuring a workflow."
            />
          )}
          {!query.isLoading && !query.error && systems.length > 0 && (
            <div className="overflow-x-auto rounded-xl border border-border-subtle bg-surface">
              <table className="w-full text-left text-sm">
                <thead className="border-b border-border-subtle bg-surface-subtle text-xs uppercase text-ink-muted">
                  <tr>
                    <th className="px-4 py-2 font-medium">Code</th>
                    <th className="px-4 py-2 font-medium">Name</th>
                    <th className="px-4 py-2 font-medium">Description</th>
                    <th className="px-4 py-2 font-medium">Status</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border-subtle">
                  {systems.map((system) => {
                    const tone: StatusTone = system.status === "active" ? "active" : "closed";
                    return (
                      <tr key={system.id} className="hover:bg-surface-subtle">
                        <td className="px-4 py-2 font-medium text-ink">{system.code}</td>
                        <td className="px-4 py-2 text-ink">{system.name}</td>
                        <td className="px-4 py-2 text-ink-muted">{system.description ?? "—"}</td>
                        <td className="px-4 py-2">
                          <StatusBadge label={system.status === "active" ? "Active" : "Inactive"} tone={tone} />
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </StandaloneShell>
  );
}
