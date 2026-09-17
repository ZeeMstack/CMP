"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";

import { Breadcrumbs } from "@/components/Breadcrumbs";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { LoadingSkeleton } from "@/components/LoadingSkeleton";
import { PageHeader } from "@/components/PageHeader";
import { StatusBadge, type StatusTone } from "@/components/StatusBadge";
import { Button } from "@/components/ui/Button";
import type { EquipmentIncidentRead } from "@/lib/api/client";
import { humanizeEnumCode } from "@/lib/format/humanize";
import { useEquipmentIncidents } from "@/lib/query/hooks";

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

function IncidentTable({ incidents, farmId }: { incidents: EquipmentIncidentRead[]; farmId: string }) {
  if (incidents.length === 0) {
    return <EmptyState title="Nothing here" description="No Equipment Incidents in this view." />;
  }
  return (
    <div className="overflow-x-auto rounded-xl border border-wl-border bg-wl-surface-raised">
      <table className="w-full text-left text-sm">
        <thead className="border-b border-wl-border bg-wl-surface-sunken text-xs uppercase text-wl-text-secondary">
          <tr>
            <th className="px-4 py-2 font-medium">Incident</th>
            <th className="px-4 py-2 font-medium">Asset</th>
            <th className="px-4 py-2 font-medium">Location</th>
            <th className="px-4 py-2 font-medium">Severity</th>
            <th className="px-4 py-2 font-medium">Status</th>
            <th className="px-4 py-2 font-medium">Opened</th>
            <th className="px-4 py-2 font-medium" />
          </tr>
        </thead>
        <tbody className="divide-y divide-wl-border">
          {incidents.map((incident) => (
            <tr key={incident.id} className="hover:bg-wl-surface-hover">
              <td className="px-4 py-2 font-medium text-wl-text">{incident.code}</td>
              <td className="px-4 py-2 text-wl-text-secondary">{incident.asset?.code ?? "—"}</td>
              <td className="px-4 py-2 text-wl-text-secondary">{incident.location?.code ?? "—"}</td>
              <td className="px-4 py-2">
                <StatusBadge label={humanizeEnumCode(incident.severity)} tone={SEVERITY_TONE[incident.severity]} />
              </td>
              <td className="px-4 py-2">
                <StatusBadge label={humanizeEnumCode(incident.status)} tone={STATUS_TONE[incident.status]} />
              </td>
              <td className="px-4 py-2 text-wl-text-secondary">{new Date(incident.opened_at).toLocaleString()}</td>
              <td className="px-4 py-2 text-right">
                <Link
                  href={`/farms/${farmId}/equipment-incidents/${incident.id}`}
                  className="text-sm font-medium text-wl-brand hover:underline"
                >
                  Open
                </Link>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** PILOT-ASSET-001: Open / Resolved+Closed tabs -- one bounded read per tab
 * (mirrors Crop Issues' `useCropIssues` list convention), never a single
 * unfiltered farm-wide fetch split client-side by every status. */
export default function EquipmentIncidentsPage() {
  const { farmId } = useParams<{ farmId: string }>();
  const [tab, setTab] = useState<"open" | "closed">("open");

  const openQuery = useEquipmentIncidents(farmId, { status: ["open", "acknowledged", "action_in_progress"] });
  const closedQuery = useEquipmentIncidents(farmId, { status: ["resolved", "closed"] });
  const activeQuery = tab === "open" ? openQuery : closedQuery;

  return (
    <div>
      <PageHeader
        title="Equipment Incidents"
        breadcrumbs={
          <Breadcrumbs items={[{ label: "Home", href: `/farms/${farmId}` }, { label: "Equipment Incidents" }]} />
        }
        actions={
          <Link
            href={`/farms/${farmId}/equipment-incidents/new`}
            className="inline-flex h-9 items-center justify-center gap-1.5 rounded-lg border border-transparent bg-wl-brand px-4 text-sm font-medium text-wl-text-on-brand transition-colors hover:bg-wl-brand-hover focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-wl-focus"
          >
            Report Incident
          </Link>
        }
      />

      <div className="mb-4 flex gap-2">
        <Button variant={tab === "open" ? "primary" : "secondary"} onClick={() => setTab("open")}>
          Open
        </Button>
        <Button variant={tab === "closed" ? "primary" : "secondary"} onClick={() => setTab("closed")}>
          Resolved &amp; Closed
        </Button>
      </div>

      {activeQuery.isLoading && <LoadingSkeleton rows={4} label="Loading equipment incidents" />}
      {!activeQuery.isLoading && activeQuery.error && (
        <ErrorState error={activeQuery.error} onRetry={() => activeQuery.refetch()} />
      )}
      {!activeQuery.isLoading && !activeQuery.error && (
        <IncidentTable incidents={activeQuery.data ?? []} farmId={farmId} />
      )}
    </div>
  );
}
