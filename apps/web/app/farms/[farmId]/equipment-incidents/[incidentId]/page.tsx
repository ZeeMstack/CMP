"use client";

import { useParams } from "next/navigation";
import { useState } from "react";

import { Breadcrumbs } from "@/components/Breadcrumbs";
import { INCIDENT_SEVERITY_TONE, INCIDENT_STATUS_TONE } from "@/components/equipment-incidents/EquipmentIncidentInspector";
import { BoundedDataRegion } from "@/components/layout/BoundedDataRegion";
import { ErrorState } from "@/components/ErrorState";
import { LoadingSkeleton } from "@/components/LoadingSkeleton";
import { PageHeader } from "@/components/PageHeader";
import { StatusBadge } from "@/components/StatusBadge";
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

/** UX-OPS-001B §8.3: the Equipment Incident investigation workspace --
 * compact context, ONE status/next-action panel (Acknowledge -> Mark
 * Action In Progress -> Resolve -> Close consolidated into a single
 * section, primary button = the natural next step, other currently-valid
 * transitions offered as secondary), Owner assignment, Corrective Work
 * links, and history in a bounded secondary disclosure. Never implies a
 * linked Work Item's completion resolves the Incident -- resolution stays
 * its own explicit command (`ResolveClosePanel`, unchanged). */
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
        compact
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
            <StatusBadge label={humanizeEnumCode(incident.severity)} tone={INCIDENT_SEVERITY_TONE[incident.severity]} />
            <StatusBadge label={humanizeEnumCode(incident.status)} tone={INCIDENT_STATUS_TONE[incident.status]} />
          </div>
        }
      />

      <IncidentContext incident={incident} />
      <StatusPanel farmId={farmId} incident={incident} />
      <AssignOwnerPanel farmId={farmId} incident={incident} />
      <CorrectiveWorkPanel farmId={farmId} incident={incident} />

      <details className="mt-2">
        <summary className="cursor-pointer text-xs font-medium uppercase tracking-wide text-wl-text-secondary">
          History
        </summary>
        <div className="mt-2">
          <HistoryPanel
            loading={historyQuery.isLoading}
            error={historyQuery.error}
            entries={historyQuery.data ?? []}
            onRetry={() => historyQuery.refetch()}
          />
        </div>
      </details>
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
          <dt className="text-xs text-wl-text-secondary">Equipment location</dt>
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

type StatusAction = "acknowledge" | "mark_action_in_progress" | "resolve" | "close";

const STATUS_ACTION_LABEL: Record<StatusAction, string> = {
  acknowledge: "Acknowledge",
  mark_action_in_progress: "Mark Action In Progress",
  resolve: "Resolve Incident",
  close: "Close Incident",
};

/** Exact same eligibility as the prior separate ActionPanel/
 * ResolveClosePanel: Acknowledge only from OPEN; Mark Action In Progress
 * from OPEN or ACKNOWLEDGED; Resolve from anything not already RESOLVED/
 * CLOSED; Close only from RESOLVED. Unchanged -- only the layout (one
 * panel, one primary + secondary buttons) and command-identity stability
 * are new. */
function availableStatusActions(status: EquipmentIncidentRead["status"]): StatusAction[] {
  const actions: StatusAction[] = [];
  if (status === "open") actions.push("acknowledge");
  if (status === "open" || status === "acknowledged") actions.push("mark_action_in_progress");
  if (status !== "resolved" && status !== "closed") actions.push("resolve");
  if (status === "resolved") actions.push("close");
  return actions;
}

function primaryStatusAction(status: EquipmentIncidentRead["status"]): StatusAction | null {
  const order: StatusAction[] = ["acknowledge", "mark_action_in_progress", "resolve", "close"];
  const available = availableStatusActions(status);
  return order.find((a) => available.includes(a)) ?? null;
}

function StatusPanel({ farmId, incident }: { farmId: string; incident: EquipmentIncidentRead }) {
  const acknowledge = useAcknowledgeEquipmentIncident(farmId);
  const actionInProgress = useMarkEquipmentIncidentActionInProgress(farmId);
  const resolve = useResolveEquipmentIncident(farmId);
  const close = useCloseEquipmentIncident(farmId);

  const available = availableStatusActions(incident.status);
  const primary = primaryStatusAction(incident.status);
  const secondary = available.filter((a) => a !== primary);

  const [active, setActive] = useState<StatusAction | null>(null);
  // UX-OPS-001B §9: minted once per active command attempt, reused across
  // a retry of the same payload -- a genuinely new action selection (or
  // Cancel + reopen) is the only thing that mints a new one.
  const [clientCommandId, setClientCommandId] = useState(() => crypto.randomUUID());
  const [resolutionNote, setResolutionNote] = useState("");
  const [closeNote, setCloseNote] = useState("");

  if (incident.status === "closed") {
    return (
      <section className="mb-6 rounded-lg border border-wl-border bg-wl-surface-raised p-4 text-sm text-wl-text-secondary">
        Closed {incident.closed_at ? new Date(incident.closed_at).toLocaleString() : ""}
        {incident.close_note && ` — ${incident.close_note}`}
      </section>
    );
  }

  function open(action: StatusAction) {
    setClientCommandId(crypto.randomUUID());
    setResolutionNote("");
    setCloseNote("");
    setActive(action);
  }
  function cancel() {
    setActive(null);
  }

  const oneClickMutation = active === "acknowledge" ? acknowledge : active === "mark_action_in_progress" ? actionInProgress : null;

  return (
    <section className="mb-6 rounded-lg border border-wl-border bg-wl-surface-raised p-4">
      <h2 className="mb-2 text-xs font-medium uppercase tracking-wide text-wl-text-secondary">Status</h2>

      {incident.status === "resolved" && (
        <p className="mb-2 text-sm text-wl-text-secondary">
          Resolved {incident.resolved_at ? new Date(incident.resolved_at).toLocaleString() : ""}
          {incident.resolution_note && ` — ${incident.resolution_note}`}
        </p>
      )}

      {!active ? (
        <div className="flex flex-wrap items-center gap-2">
          {primary && (
            <Button variant="primary" onClick={() => open(primary)}>
              {STATUS_ACTION_LABEL[primary]}
            </Button>
          )}
          {secondary.length > 0 && (
            <div className="flex flex-wrap gap-2 border-l border-wl-border pl-2">
              {secondary.map((action) => (
                <Button key={action} variant="secondary" onClick={() => open(action)}>
                  {STATUS_ACTION_LABEL[action]}
                </Button>
              ))}
            </div>
          )}
        </div>
      ) : active === "resolve" ? (
        <div className="flex flex-col gap-2">
          <label className="flex flex-col gap-1">
            <span className={labelClass}>Resolution note</span>
            <textarea className={`${inputClass} min-h-16`} value={resolutionNote} onChange={(e) => setResolutionNote(e.target.value)} />
          </label>
          {resolve.error && <ErrorState error={resolve.error} />}
          <div className="flex gap-2">
            <Button variant="secondary" onClick={cancel} disabled={resolve.isPending}>
              Cancel
            </Button>
            <Button
              variant="primary"
              disabled={resolve.isPending || !resolutionNote.trim()}
              onClick={() =>
                resolve.mutate(
                  { incidentId: incident.id, payload: { client_command_id: clientCommandId, resolution_note: resolutionNote.trim() } },
                  { onSuccess: cancel },
                )
              }
            >
              {resolve.isPending ? "Resolving…" : "Confirm Resolve"}
            </Button>
          </div>
        </div>
      ) : active === "close" ? (
        <div className="flex flex-col gap-2">
          <label className="flex flex-col gap-1">
            <span className={labelClass}>Close note (optional)</span>
            <textarea className={`${inputClass} min-h-16`} value={closeNote} onChange={(e) => setCloseNote(e.target.value)} />
          </label>
          {close.error && <ErrorState error={close.error} />}
          <div className="flex gap-2">
            <Button variant="secondary" onClick={cancel} disabled={close.isPending}>
              Cancel
            </Button>
            <Button
              variant="primary"
              disabled={close.isPending}
              onClick={() =>
                close.mutate(
                  { incidentId: incident.id, payload: { client_command_id: clientCommandId, close_note: closeNote.trim() || null } },
                  { onSuccess: cancel },
                )
              }
            >
              {close.isPending ? "Closing…" : "Confirm Close"}
            </Button>
          </div>
        </div>
      ) : (
        oneClickMutation && (
          <div className="flex flex-col gap-2">
            {oneClickMutation.error && <ErrorState error={oneClickMutation.error} />}
            <div className="flex gap-2">
              <Button variant="secondary" onClick={cancel} disabled={oneClickMutation.isPending}>
                Cancel
              </Button>
              <Button
                variant="primary"
                disabled={oneClickMutation.isPending}
                onClick={() =>
                  oneClickMutation.mutate(
                    { incidentId: incident.id, payload: { client_command_id: clientCommandId } },
                    { onSuccess: cancel },
                  )
                }
              >
                {oneClickMutation.isPending ? "Saving…" : `Confirm ${STATUS_ACTION_LABEL[active]}`}
              </Button>
            </div>
          </div>
        )
      )}
    </section>
  );
}

function AssignOwnerPanel({ farmId, incident }: { farmId: string; incident: EquipmentIncidentRead }) {
  const assign = useAssignEquipmentIncident(farmId);
  const [assigning, setAssigning] = useState(false);
  const [ownerId, setOwnerId] = useState("");
  const [clientCommandId, setClientCommandId] = useState(() => crypto.randomUUID());

  if (incident.status === "resolved" || incident.status === "closed") return null;

  return (
    <section className="mb-6 rounded-lg border border-wl-border bg-wl-surface-raised p-4">
      <h2 className="mb-2 text-xs font-medium uppercase tracking-wide text-wl-text-secondary">Owner</h2>
      <p className="mb-2 text-sm text-wl-text">{incident.assigned_owner_user_id ? "Assigned" : "Unassigned"}</p>
      {!assigning ? (
        <Button
          variant="secondary"
          onClick={() => {
            setClientCommandId(crypto.randomUUID());
            setAssigning(true);
          }}
        >
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
                  { incidentId: incident.id, payload: { client_command_id: clientCommandId, assigned_owner_user_id: ownerId.trim() } },
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

function HistoryPanel({
  loading, error, entries, onRetry,
}: {
  loading: boolean;
  error: unknown;
  entries: { id: string; action: string; effective_time: string }[];
  onRetry: () => void;
}) {
  if (loading) return <LoadingSkeleton rows={2} label="Loading history" />;
  if (error) return <ErrorState error={error} onRetry={onRetry} />;
  if (entries.length === 0) return <p className="text-sm text-wl-text-secondary">No history yet.</p>;
  return (
    <BoundedDataRegion label="Incident history">
      <ul className="divide-y divide-wl-border">
        {entries.map((entry) => (
          <li key={entry.id} className="flex items-center justify-between gap-3 px-3.5 py-2 text-sm">
            <span className="text-wl-text">{humanizeEnumCode(entry.action)}</span>
            <span className="text-xs text-wl-text-secondary">{new Date(entry.effective_time).toLocaleString()}</span>
          </li>
        ))}
      </ul>
    </BoundedDataRegion>
  );
}
