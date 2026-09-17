"use client";

import { useState } from "react";

import { Button } from "@/components/ui/Button";
import { ErrorState } from "@/components/ErrorState";
import { LoadingSkeleton } from "@/components/LoadingSkeleton";
import { StatusBadge } from "@/components/StatusBadge";
import type { CropBatchRead } from "@/lib/api/client";
import { useAssignBatchProtocol, useBatchProtocolStatus, useGrowingProtocols, useProtocolVersions } from "@/lib/query/hooks";

/** PILOT-AGRO-001B section 15 (Part 2): the compact Protocol section on the
 * Batch page -- never a redesign of the Batch page itself. Shows current
 * assignment + deterministic due/deviation status, or an Assign action when
 * none is assigned. FROZEN: assignment/reassignment never alters Batch
 * stage or crop state -- this panel only ever calls `assignBatchProtocol`. */
export function BatchProtocolPanel({ farmId, batch }: { farmId: string; batch: CropBatchRead }) {
  const statusQuery = useBatchProtocolStatus(farmId, batch.id);
  const [assigning, setAssigning] = useState(false);

  if (statusQuery.isLoading) return <LoadingSkeleton rows={2} label="Loading protocol status" />;
  if (statusQuery.error) return <ErrorState error={statusQuery.error} onRetry={() => statusQuery.refetch()} />;
  const status = statusQuery.data;
  if (!status) return null;

  if (assigning || !status.current_assignment) {
    return (
      <div className="flex flex-col gap-3">
        {!status.current_assignment && !assigning && (
          <div className="rounded-lg border border-dashed border-wl-border bg-wl-surface-raised p-4">
            <p className="text-sm font-medium text-wl-text">No growing protocol assigned</p>
            <p className="mt-1 text-xs text-wl-text-secondary">
              No care/observation guidance will surface for this Batch until one is assigned.
            </p>
            <Button variant="primary" className="mt-3" onClick={() => setAssigning(true)}>
              Assign Protocol
            </Button>
          </div>
        )}
        {assigning && (
          <AssignProtocolForm
            farmId={farmId}
            batch={batch}
            isReassign={Boolean(status.current_assignment)}
            onDone={() => setAssigning(false)}
            onCancel={() => setAssigning(false)}
          />
        )}
      </div>
    );
  }

  const overdueCount = status.due_observation_requirements.filter((r) => r.is_overdue).length;
  const dueCount = status.due_observation_requirements.filter((r) => r.is_due).length;
  const protocolState = overdueCount > 0 ? "overdue" : dueCount > 0 ? "due" : "on_track";
  const stateBadge = { on_track: ["On track", "active"], due: ["Due", "attention"], overdue: ["Overdue", "critical"] } as const;
  const [stateLabel, stateTone] = stateBadge[protocolState];

  return (
    <div className="flex flex-col gap-4 rounded-lg border border-wl-border bg-wl-surface-raised p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-sm font-medium text-wl-text">
            {status.protocol?.name} · v{status.protocol_version?.version_number}
          </p>
          <p className="mt-0.5 text-xs text-wl-text-secondary">
            Assigned {new Date(status.current_assignment.assigned_at).toLocaleString()}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <StatusBadge label={stateLabel} tone={stateTone} />
          <Button variant="secondary" onClick={() => setAssigning(true)}>
            Change Protocol
          </Button>
        </div>
      </div>

      {status.current_stage_category && (
        <p className="text-xs text-wl-text-secondary">
          Current stage: {status.current_stage_category}
          {status.days_in_stage !== null ? ` · ${status.days_in_stage} day(s) in stage` : ""}
        </p>
      )}

      {status.due_observation_requirements.length === 0 ? (
        <p className="text-sm text-wl-text-secondary">No observations required at this stage.</p>
      ) : (
        <ul className="divide-y divide-wl-border">
          {status.due_observation_requirements.map((r) => (
            <li key={r.requirement.id} className="flex items-center justify-between py-2 text-sm">
              <div>
                <span className="text-wl-text">{r.observation_definition_name}</span>
                {r.requirement.requirement_level === "required" && (
                  <span className="ml-1.5 text-xs text-wl-text-secondary">(required)</span>
                )}
              </div>
              {r.is_overdue ? (
                <StatusBadge label="Overdue" tone="critical" />
              ) : r.is_due ? (
                <StatusBadge label="Due" tone="attention" />
              ) : (
                <StatusBadge label="Satisfied" tone="active" />
              )}
            </li>
          ))}
        </ul>
      )}

      {status.open_crop_issue_count > 0 && (
        <p className="text-sm text-wl-flag-fg">
          {status.open_crop_issue_count} open crop issue{status.open_crop_issue_count === 1 ? "" : "s"} for this Batch.
        </p>
      )}
    </div>
  );
}

function AssignProtocolForm({
  farmId,
  batch,
  isReassign,
  onDone,
  onCancel,
}: {
  farmId: string;
  batch: CropBatchRead;
  isReassign: boolean;
  onDone: () => void;
  onCancel: () => void;
}) {
  const protocolsQuery = useGrowingProtocols();
  const [protocolId, setProtocolId] = useState<string>("");
  const versionsQuery = useProtocolVersions(protocolId || undefined);
  const [confirming, setConfirming] = useState(false);
  const assignMutation = useAssignBatchProtocol(farmId, batch.id);

  const compatibleProtocols = (protocolsQuery.data ?? []).filter(
    (p) => p.crop_id === batch.crop.id && (p.variety_id === null || p.variety_id === batch.variety?.id),
  );
  const activeVersion = (versionsQuery.data ?? []).find((v) => v.state === "active") ?? null;

  function confirmAssign() {
    if (!activeVersion) return;
    assignMutation.mutate(
      { client_command_id: crypto.randomUUID(), growing_protocol_version_id: activeVersion.id },
      { onSuccess: onDone },
    );
  }

  return (
    <div className="flex flex-col gap-3 rounded-lg border border-wl-border bg-wl-surface-raised p-4">
      <p className="text-sm font-medium text-wl-text">{isReassign ? "Change Protocol" : "Assign Protocol"}</p>
      {compatibleProtocols.length === 0 ? (
        <p className="text-sm text-wl-text-secondary">
          No Growing Protocol registered for {batch.crop.common_name}
          {batch.variety ? ` / ${batch.variety.name}` : ""} yet.
        </p>
      ) : (
        <>
          <label className="flex flex-col gap-1 text-sm">
            <span className="text-wl-text-secondary">Protocol</span>
            <select
              value={protocolId}
              onChange={(e) => {
                setProtocolId(e.target.value);
                setConfirming(false);
              }}
              className="min-h-11 rounded-md border border-wl-border bg-wl-surface px-3 text-sm text-wl-text"
            >
              <option value="">Select a protocol…</option>
              {compatibleProtocols.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.code} — {p.name}
                </option>
              ))}
            </select>
          </label>

          {protocolId && !versionsQuery.isLoading && !activeVersion && (
            <p className="text-sm text-wl-text-secondary">This protocol has no ACTIVE version yet.</p>
          )}

          {protocolId && activeVersion && (
            <>
              <p className="text-sm text-wl-text">
                Assigns v{activeVersion.version_number} (active since{" "}
                {activeVersion.activated_at ? new Date(activeVersion.activated_at).toLocaleDateString() : "—"}).
              </p>
              {!confirming ? (
                <Button variant="primary" className="self-start" onClick={() => setConfirming(true)}>
                  {isReassign ? "Change to this version" : "Assign this version"}
                </Button>
              ) : (
                <div className="rounded-md bg-wl-hold-bg p-3 text-sm text-wl-hold-fg">
                  <p>
                    {isReassign
                      ? "This changes the protocol for future guidance. Historical assignment remains preserved."
                      : "This assigns the protocol for future guidance to this Batch."}
                  </p>
                  <div className="mt-2 flex gap-2">
                    <Button variant="secondary" onClick={() => setConfirming(false)} disabled={assignMutation.isPending}>
                      Back
                    </Button>
                    <Button variant="primary" onClick={confirmAssign} disabled={assignMutation.isPending}>
                      {assignMutation.isPending ? "Assigning…" : "Confirm"}
                    </Button>
                  </div>
                </div>
              )}
            </>
          )}
        </>
      )}
      {assignMutation.error && <ErrorState error={assignMutation.error} />}
      <Button variant="secondary" className="self-start" onClick={onCancel} disabled={assignMutation.isPending}>
        Cancel
      </Button>
    </div>
  );
}
