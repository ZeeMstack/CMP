import Link from "next/link";

import { InspectorEmptyState, InspectorShell } from "@/components/layout/InspectorShell";
import { StatusBadge, type StatusTone } from "@/components/StatusBadge";
import type { EquipmentIncidentRead } from "@/lib/api/client";
import { humanizeEnumCode } from "@/lib/format/humanize";

export const INCIDENT_STATUS_TONE: Record<EquipmentIncidentRead["status"], StatusTone> = {
  open: "attention",
  acknowledged: "attention",
  action_in_progress: "attention",
  resolved: "active",
  closed: "closed",
};
export const INCIDENT_SEVERITY_TONE: Record<EquipmentIncidentRead["severity"], StatusTone> = {
  low: "neutral",
  medium: "attention",
  high: "attention",
  critical: "critical",
};

const NEXT_ACTION_LABEL: Record<EquipmentIncidentRead["status"], string | null> = {
  open: "Acknowledge",
  acknowledged: "Mark Action In Progress",
  action_in_progress: "Resolve Incident",
  resolved: "Close Incident",
  closed: null,
};

/** UX-OPS-001B: the Equipment Incidents queue's selected-item inspector --
 * compact identity/context facts plus the current status's own next action,
 * linking into the full investigation workspace (which owns the actual
 * command forms/payloads, unchanged). Never renames "Potentially impacted
 * area" to "Affected crop" (ticket §8.1 -- an Incident is not a Crop
 * Issue). */
export function EquipmentIncidentInspector({
  incident, farmId, onClose,
}: {
  incident: EquipmentIncidentRead | null;
  farmId: string;
  onClose: () => void;
}) {
  if (!incident) return <InspectorEmptyState />;

  const href = `/farms/${farmId}/equipment-incidents/${incident.id}`;
  const nextActionLabel = NEXT_ACTION_LABEL[incident.status];

  return (
    <InspectorShell
      title={incident.code}
      subtitle={incident.asset ? `${incident.asset.name} (${incident.asset.code})` : undefined}
      status={<StatusBadge label={humanizeEnumCode(incident.severity)} tone={INCIDENT_SEVERITY_TONE[incident.severity]} />}
      onClose={onClose}
    >
      <div className="flex items-center gap-2">
        <StatusBadge label={humanizeEnumCode(incident.status)} tone={INCIDENT_STATUS_TONE[incident.status]} />
        {incident.assigned_owner_user_id && <span className="text-xs text-wl-text-secondary">Owner assigned</span>}
      </div>
      <dl className="grid grid-cols-1 gap-2 text-sm">
        <div>
          <dt className="text-xs text-wl-text-secondary">Category</dt>
          <dd className="text-wl-text">{humanizeEnumCode(incident.category)}</dd>
        </div>
        <div>
          <dt className="text-xs text-wl-text-secondary">Equipment location</dt>
          <dd className="text-wl-text">{incident.location ? `${incident.location.code} · ${incident.location.name}` : "—"}</dd>
        </div>
        <div>
          <dt className="text-xs text-wl-text-secondary">Potentially impacted area</dt>
          <dd className="text-wl-text">
            {incident.potentially_impacted_location
              ? `${incident.potentially_impacted_location.code} · ${incident.potentially_impacted_location.name}`
              : "—"}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-wl-text-secondary">Detected</dt>
          <dd className="text-wl-text">{new Date(incident.detected_at).toLocaleString()}</dd>
        </div>
      </dl>
      <Link href={href} className="inline-block text-sm font-medium text-wl-brand hover:underline">
        {nextActionLabel ? nextActionLabel : "Open investigation"}
      </Link>
    </InspectorShell>
  );
}
