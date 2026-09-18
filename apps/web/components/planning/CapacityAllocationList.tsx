"use client";

import { useState } from "react";

import { Button } from "@/components/ui/Button";
import { CapacityAllocationUpdateForm } from "@/components/planning/CapacityAllocationUpdateForm";
import type { ProductionCapacityAllocationRead } from "@/lib/api/client";
import { AppError } from "@/lib/errors/adapter";
import { formatPlanDate } from "@/lib/format/planDate";
import { useCancelCapacityAllocation, useUpdateCapacityAllocation } from "@/lib/query/hooks";

/** PILOT-PLAN-001B section 14: Update/Cancel an existing allocation.
 * Cancellation is deliberate (a confirm step, mirroring the Requirement
 * detail page's own Close/Cancel pattern) and never deletes the planning
 * record or touches actual Occupancy -- see the frozen "Planned vs Actual"
 * distinction. */
export function CapacityAllocationList({
  farmId,
  locationId,
  allocations,
}: {
  farmId: string;
  locationId: string;
  allocations: ProductionCapacityAllocationRead[];
}) {
  const [editingId, setEditingId] = useState<string | null>(null);
  const [confirmingCancelId, setConfirmingCancelId] = useState<string | null>(null);

  if (allocations.length === 0) {
    return <p className="text-sm text-wl-text-secondary">No allocations overlap this window.</p>;
  }

  return (
    <ul className="divide-y divide-wl-border rounded-md border border-wl-border">
      {allocations.map((allocation) => (
        <li key={allocation.id} className="p-3 text-sm">
          {editingId === allocation.id ? (
            <AllocationEditRow
              farmId={farmId}
              locationId={locationId}
              allocation={allocation}
              onDone={() => setEditingId(null)}
              onCancel={() => setEditingId(null)}
            />
          ) : (
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div>
                <p className="font-medium text-wl-text">
                  {allocation.code} · {formatPlanDate(allocation.planned_start_date)} – {formatPlanDate(allocation.planned_end_date)}{" "}
                  (end exclusive)
                </p>
                <p className="text-xs text-wl-text-secondary">
                  {allocation.planned_capacity_amount} positions
                  {allocation.notes ? ` · ${allocation.notes}` : ""}
                </p>
              </div>
              {allocation.status === "active" ? (
                confirmingCancelId === allocation.id ? (
                  <CancelConfirm
                    farmId={farmId}
                    locationId={locationId}
                    allocationId={allocation.id}
                    onDone={() => setConfirmingCancelId(null)}
                    onBack={() => setConfirmingCancelId(null)}
                  />
                ) : (
                  <div className="flex gap-2">
                    <Button variant="secondary" onClick={() => setEditingId(allocation.id)}>
                      Update Allocation
                    </Button>
                    <Button variant="danger" onClick={() => setConfirmingCancelId(allocation.id)}>
                      Cancel Allocation
                    </Button>
                  </div>
                )
              ) : (
                <span className="text-xs text-wl-text-tertiary">Cancelled</span>
              )}
            </div>
          )}
        </li>
      ))}
    </ul>
  );
}

function AllocationEditRow({
  farmId,
  locationId,
  allocation,
  onDone,
  onCancel,
}: {
  farmId: string;
  locationId: string;
  allocation: ProductionCapacityAllocationRead;
  onDone: () => void;
  onCancel: () => void;
}) {
  const updateMutation = useUpdateCapacityAllocation(farmId, allocation.id, locationId);
  return (
    <CapacityAllocationUpdateForm
      allocation={allocation}
      isSubmitting={updateMutation.isPending}
      serverError={updateMutation.error instanceof AppError ? updateMutation.error.message : null}
      onCancel={onCancel}
      onSubmit={(payload) => updateMutation.mutate(payload, { onSuccess: onDone })}
    />
  );
}

function CancelConfirm({
  farmId,
  locationId,
  allocationId,
  onDone,
  onBack,
}: {
  farmId: string;
  locationId: string;
  allocationId: string;
  onDone: () => void;
  onBack: () => void;
}) {
  const cancelMutation = useCancelCapacityAllocation(farmId, allocationId, locationId);
  return (
    <div className="flex flex-col items-end gap-2">
      <p className="text-xs text-wl-text-secondary">
        This stops the allocation from consuming planned capacity. It does not delete the record or change actual
        occupancy.
      </p>
      <div className="flex gap-2">
        <Button variant="secondary" onClick={onBack} disabled={cancelMutation.isPending}>
          Back
        </Button>
        <Button
          variant="danger"
          disabled={cancelMutation.isPending}
          onClick={() => cancelMutation.mutate({ client_command_id: crypto.randomUUID() }, { onSuccess: onDone })}
        >
          {cancelMutation.isPending ? "Cancelling…" : "Confirm Cancel"}
        </Button>
      </div>
      {cancelMutation.error && (
        <p role="alert" className="text-xs text-red-700">
          {cancelMutation.error instanceof AppError ? cancelMutation.error.message : "Something went wrong."}
        </p>
      )}
    </div>
  );
}
