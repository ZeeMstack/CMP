"use client";

import { useParams } from "next/navigation";
import { useState } from "react";

import { Breadcrumbs } from "@/components/Breadcrumbs";
import { ErrorState } from "@/components/ErrorState";
import { LoadingSkeleton } from "@/components/LoadingSkeleton";
import { PageHeader } from "@/components/PageHeader";
import { StatusBadge, type StatusTone } from "@/components/StatusBadge";
import { Button } from "@/components/ui/Button";
import { CreateWorkItemForm } from "@/components/work-items/CreateWorkItemForm";
import { WorkItemRow } from "@/components/work-items/WorkItemRow";
import type { EquipmentIncidentRead, FarmWorkItemRead } from "@/lib/api/client";
import { humanizeEnumCode } from "@/lib/format/humanize";
import {
  useAcknowledgeEquipmentIncident,
  useAssignEquipmentIncident,
  useCloseEquipmentIncident,
  useCreateWorkItem,
  useEquipmentIncident,
  useEquipmentIncidentHistory,
  useMarkEquipmentIncidentActionInProgress,
  useResolveEquipmentIncident,
} from "@/lib/query/hooks";

const inputClass =
  "min-h-10 w-full rounded-md border border-wl-border bg-wl-surface px-2.5 text-sm text-wl-text focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-wl-focus";
const labelClass = "text-xs font-medium text-wl-text-secondary";

const STATUS_TONE: Record<EquipmentIncidentRead["status"], StatusTone> = {
  open: "attention",
  acknowledged: "attention",
  action_in_progress: "attention",
  resolved: "active",
  closed: "closed",
};
const SEVERITY_TONE: Record<EquipmentIncidentRead["severity"], StatusTone> = {
  low: "neutral",
  medium: "attention",
  high: "attention",
  critical: "critical",
};

/** PILOT-ASSET-001: the Equipment Incident workspace -- mirrors
 * crop-issues/[issueId]/page.tsx's overall shape (context, deliberately
 * separate per-status action panels, corrective Work Item linking, status
 * history), never one generic "Update Incident" form. Actions are shown
 * deliberately per status (OPEN -> ACKNOWLEDGED -> ACTION_IN_PROGRESS ->
 * RESOLVED -> CLOSED) -- this codebase has no frontend permission hook
 * anywhere, so an unauthorized click is caught by the backend's own 403. */
export default function EquipmentIncidentWorkspacePage() {
  const { farmId, incidentId } = useParams<{ farmId: string; incidentId: string }>();
  const incidentQuery = useEquipmentIncident(farmId, incidentId);
  const historyQuery = useEquipmentIncidentHistory(farmId, incidentId);

  if (incidentQuery.isLoading) return <LoadingSkeleton rows={6} label="Loading equipment incident" />;
  if (incidentQuery.error) return <ErrorState error={incidentQuery.error} onRetry={() => incidentQuery.refetch()} />;
  const incident = incidentQuery.data;
  if (!incident) return null;

  return (
    <div>
      <PageHeader
        title={incident.code}
        description={incident.description}
        breadcrumbs={
          <Breadcrumbs
            items={[
              { label: "Home", href: `/farms/${farmId}` },
              { label: "Equipment Incidents", href: `/farms/${farmId}/equipment-incidents` },
              { label: incident.code },
            ]}
          />
        }
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <StatusBadge label={humanizeEnumCode(incident.severity)} tone={SEVERITY_TONE[incident.severity]} />
            <StatusBadge label={humanizeEnumCode(incident.status)} tone={STATUS_TONE[incident.status]} />
          </div>
        }
      />

      <IncidentContext incident={incident} />
      <ActionPanel farmId={farmId} incident={incident} />
      <AssignOwnerPanel farmId={farmId} incident={incident} />
      <CorrectiveWorkPanel farmId={farmId} incident={incident} />
      <ResolveClosePanel farmId={farmId} incident={incident} />
      <HistoryPanel loading={historyQuery.isLoading} error={historyQuery.error} entries={historyQuery.data ?? []} onRetry={() => historyQuery.refetch()} />
    </div>
  );
}

function IncidentContext({ incident }: { incident: EquipmentIncidentRead }) {
  return (
    <section className="mb-6 rounded-lg border border-wl-border bg-wl-surface-raised p-4">
      <dl className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <div>
          <dt className="text-xs text-wl-text-secondary">Asset</dt>
          <dd className="text-sm text-wl-text">{incident.asset ? `${incident.asset.name} (${incident.asset.code})` : "—"}</dd>
        </div>
        <div>
          <dt className="text-xs text-wl-text-secondary">Category</dt>
          <dd className="text-sm text-wl-text">{humanizeEnumCode(incident.category)}</dd>
        </div>
        <div>
          <dt className="text-xs text-wl-text-secondary">Location</dt>
          <dd className="text-sm text-wl-text">{incident.location ? `${incident.location.code} · ${incident.location.name}` : "—"}</dd>
        </div>
        <div>
          {/* PILOT-ASSET-001: NEVER "Affected crop" -- this is a possible
              operational blast radius, not a confirmed crop impact. */}
          <dt className="text-xs text-wl-text-secondary">Potentially impacted area</dt>
          <dd className="text-sm text-wl-text">
            {incident.potentially_impacted_location
              ? `${incident.potentially_impacted_location.code} · ${incident.potentially_impacted_location.name}`
              : "—"}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-wl-text-secondary">Detected</dt>
          <dd className="text-sm text-wl-text">{new Date(incident.detected_at).toLocaleString()}</dd>
        </div>
        <div>
          <dt className="text-xs text-wl-text-secondary">Opened</dt>
          <dd className="text-sm text-wl-text">{new Date(incident.opened_at).toLocaleString()}</dd>
        </div>
        {incident.notes && (
          <div className="sm:col-span-2">
            <dt className="text-xs text-wl-text-secondary">Notes</dt>
            <dd className="text-sm text-wl-text">{incident.notes}</dd>
          </div>
        )}
      </dl>
    </section>
  );
}

/** Acknowledge / Mark Action In Progress -- plain one-click commands, no
 * fields, mirroring `WorkItemRow`'s own "Start"/"Resume" buttons. */
function ActionPanel({ farmId, incident }: { farmId: string; incident: EquipmentIncidentRead }) {
  const acknowledge = useAcknowledgeEquipmentIncident(farmId);
  const actionInProgress = useMarkEquipmentIncidentActionInProgress(farmId);

  const canAcknowledge = incident.status === "open";
  const canMarkInProgress = incident.status === "open" || incident.status === "acknowledged";
  if (!canAcknowledge && !canMarkInProgress) return null;

  return (
    <section className="mb-6 flex flex-wrap items-center gap-2">
      {canAcknowledge && (
        <Button
          variant="secondary"
          disabled={acknowledge.isPending}
          onClick={() => acknowledge.mutate({ incidentId: incident.id, payload: { client_command_id: crypto.randomUUID() } })}
        >
          {acknowledge.isPending ? "Acknowledging…" : "Acknowledge"}
        </Button>
      )}
      {canMarkInProgress && (
        <Button
          variant="secondary"
          disabled={actionInProgress.isPending}
          onClick={() => actionInProgress.mutate({ incidentId: incident.id, payload: { client_command_id: crypto.randomUUID() } })}
        >
          {actionInProgress.isPending ? "Saving…" : "Mark Action In Progress"}
        </Button>
      )}
      {(acknowledge.error || actionInProgress.error) && (
        <ErrorState error={acknowledge.error ?? actionInProgress.error} />
      )}
    </section>
  );
}

function AssignOwnerPanel({ farmId, incident }: { farmId: string; incident: EquipmentIncidentRead }) {
  const assign = useAssignEquipmentIncident(farmId);
  const [assigning, setAssigning] = useState(false);
  const [ownerId, setOwnerId] = useState("");

  if (incident.status === "resolved" || incident.status === "closed") return null;

  return (
    <section className="mb-6 rounded-lg border border-wl-border bg-wl-surface-raised p-4">
      <h2 className="mb-2 text-xs font-medium uppercase tracking-wide text-wl-text-secondary">Owner</h2>
      <p className="mb-2 text-sm text-wl-text">{incident.assigned_owner_user_id ? "Assigned" : "Unassigned"}</p>
      {!assigning ? (
        <Button variant="secondary" onClick={() => setAssigning(true)}>
          {incident.assigned_owner_user_id ? "Reassign" : "Assign Owner"}
        </Button>
      ) : (
        <div className="flex flex-col gap-2">
          <label className="flex flex-col gap-1">
            <span className={labelClass}>Owner user id</span>
            <input className={inputClass} value={ownerId} onChange={(e) => setOwnerId(e.target.value)} placeholder="User id" />
          </label>
          {assign.error && <ErrorState error={assign.error} />}
          <div className="flex gap-2">
            <Button variant="secondary" onClick={() => setAssigning(false)} disabled={assign.isPending}>
              Cancel
            </Button>
            <Button
              variant="primary"
              disabled={assign.isPending || !ownerId.trim()}
              onClick={() =>
                assign.mutate(
                  { incidentId: incident.id, payload: { client_command_id: crypto.randomUUID(), assigned_owner_user_id: ownerId.trim() } },
                  { onSuccess: () => setAssigning(false) },
                )
              }
            >
              {assign.isPending ? "Saving…" : "Confirm"}
            </Button>
          </div>
        </div>
      )}
    </section>
  );
}

function CorrectiveWorkPanel({ farmId, incident }: { farmId: string; incident: EquipmentIncidentRead }) {
  const [assigning, setAssigning] = useState(false);
  const [created, setCreated] = useState<FarmWorkItemRead | null>(null);
  const createWorkItem = useCreateWorkItem(farmId);

  return (
    <section className="mb-6">
      <h2 className="mb-2 text-xs font-medium uppercase tracking-wide text-wl-text-secondary">Corrective work</h2>
      {created ? (
        <div className="overflow-x-auto rounded-xl border border-wl-border bg-wl-surface-raised">
          <table className="w-full text-left text-sm">
            <tbody className="divide-y divide-wl-border">
              <WorkItemRow item={created} farmId={farmId} />
            </tbody>
          </table>
        </div>
      ) : !assigning ? (
        <Button variant="secondary" onClick={() => setAssigning(true)}>
          Assign Corrective Work
        </Button>
      ) : (
        <CreateWorkItemForm
          lockedEquipmentIncident={{ id: incident.id, code: incident.code }}
          isSubmitting={createWorkItem.isPending}
          serverError={createWorkItem.error ? createWorkItem.error.message : null}
          onCancel={() => setAssigning(false)}
          onSubmit={(payload) => createWorkItem.mutate(payload, { onSuccess: (item) => setCreated(item) })}
        />
      )}
    </section>
  );
}

function ResolveClosePanel({ farmId, incident }: { farmId: string; incident: EquipmentIncidentRead }) {
  const resolve = useResolveEquipmentIncident(farmId);
  const close = useCloseEquipmentIncident(farmId);
  const [resolving, setResolving] = useState(false);
  const [closing, setClosing] = useState(false);
  const [resolutionNote, setResolutionNote] = useState("");
  const [closeNote, setCloseNote] = useState("");

  if (incident.status === "closed") {
    return (
      <section className="rounded-lg border border-wl-border bg-wl-surface-raised p-4 text-sm text-wl-text-secondary">
        Closed {incident.closed_at ? new Date(incident.closed_at).toLocaleString() : ""}
        {incident.close_note && ` — ${incident.close_note}`}
      </section>
    );
  }

  return (
    <section className="rounded-lg border border-wl-border bg-wl-surface-raised p-4">
      <h2 className="mb-2 text-xs font-medium uppercase tracking-wide text-wl-text-secondary">Resolve / Close</h2>
      {incident.status !== "resolved" && (
        <>
          {!resolving ? (
            <Button variant="secondary" onClick={() => setResolving(true)}>
              Resolve Incident
            </Button>
          ) : (
            <div className="flex flex-col gap-2">
              <label className="flex flex-col gap-1">
                <span className={labelClass}>Resolution note</span>
                <textarea className={`${inputClass} min-h-16`} value={resolutionNote} onChange={(e) => setResolutionNote(e.target.value)} />
              </label>
              {resolve.error && <ErrorState error={resolve.error} />}
              <div className="flex gap-2">
                <Button variant="secondary" onClick={() => setResolving(false)} disabled={resolve.isPending}>
                  Cancel
                </Button>
                <Button
                  variant="primary"
                  disabled={resolve.isPending || !resolutionNote.trim()}
                  onClick={() =>
                    resolve.mutate(
                      { incidentId: incident.id, payload: { client_command_id: crypto.randomUUID(), resolution_note: resolutionNote.trim() } },
                      { onSuccess: () => setResolving(false) },
                    )
                  }
                >
                  {resolve.isPending ? "Resolving…" : "Confirm Resolve"}
                </Button>
              </div>
            </div>
          )}
        </>
      )}
      {incident.status === "resolved" && (
        <>
          <p className="mb-2 text-sm text-wl-text-secondary">
            Resolved {incident.resolved_at ? new Date(incident.resolved_at).toLocaleString() : ""}
            {incident.resolution_note && ` — ${incident.resolution_note}`}
          </p>
          {!closing ? (
            <Button variant="secondary" onClick={() => setClosing(true)}>
              Close Incident
            </Button>
          ) : (
            <div className="flex flex-col gap-2">
              <label className="flex flex-col gap-1">
                <span className={labelClass}>Close note (optional)</span>
                <textarea className={`${inputClass} min-h-16`} value={closeNote} onChange={(e) => setCloseNote(e.target.value)} />
              </label>
              {close.error && <ErrorState error={close.error} />}
              <div className="flex gap-2">
                <Button variant="secondary" onClick={() => setClosing(false)} disabled={close.isPending}>
                  Cancel
                </Button>
                <Button
                  variant="primary"
                  disabled={close.isPending}
                  onClick={() =>
                    close.mutate(
                      { incidentId: incident.id, payload: { client_command_id: crypto.randomUUID(), close_note: closeNote.trim() || null } },
                      { onSuccess: () => setClosing(false) },
                    )
                  }
                >
                  {close.isPending ? "Closing…" : "Confirm Close"}
                </Button>
              </div>
            </div>
          )}
        </>
      )}
    </section>
  );
}

function HistoryPanel({
  loading, error, entries, onRetry,
}: {
  loading: boolean;
  error: unknown;
  entries: { id: string; action: string; effective_time: string }[];
  onRetry: () => void;
}) {
  return (
    <section className="mt-6">
      <h2 className="mb-2 text-xs font-medium uppercase tracking-wide text-wl-text-secondary">History</h2>
      {loading && <LoadingSkeleton rows={2} label="Loading history" />}
      {!loading && Boolean(error) && <ErrorState error={error} onRetry={onRetry} />}
      {!loading && !error && entries.length === 0 && <p className="text-sm text-wl-text-secondary">No history yet.</p>}
      {!loading && !error && entries.length > 0 && (
        <ul className="divide-y divide-wl-border rounded-xl border border-wl-border bg-wl-surface-raised">
          {entries.map((entry) => (
            <li key={entry.id} className="flex items-center justify-between gap-3 px-4 py-2 text-sm">
              <span className="text-wl-text">{humanizeEnumCode(entry.action)}</span>
              <span className="text-xs text-wl-text-secondary">{new Date(entry.effective_time).toLocaleString()}</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
