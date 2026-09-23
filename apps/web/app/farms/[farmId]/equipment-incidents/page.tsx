"use client";

import Link from "next/link";
import { useParams } from "next/navigation";

import { Breadcrumbs } from "@/components/Breadcrumbs";
import { EmptyState } from "@/components/EmptyState";
import { EquipmentIncidentInspector, INCIDENT_SEVERITY_TONE, INCIDENT_STATUS_TONE } from "@/components/equipment-incidents/EquipmentIncidentInspector";
import { BoundedDataRegion } from "@/components/layout/BoundedDataRegion";
import { InspectorEmptyState } from "@/components/layout/InspectorShell";
import { QueueList, QueueRow } from "@/components/layout/QueueRow";
import { SplitWorkspace } from "@/components/layout/SplitWorkspace";
import { ViewTabs, type ViewTabItem } from "@/components/layout/ViewTabs";
import { ErrorState } from "@/components/ErrorState";
import { LoadingSkeleton } from "@/components/LoadingSkeleton";
import { PageHeader } from "@/components/PageHeader";
import { StatusBadge } from "@/components/StatusBadge";
import type { EquipmentIncidentStatus } from "@/lib/api/client";
import { humanizeEnumCode } from "@/lib/format/humanize";
import { useViewState } from "@/lib/navigation/useViewState";
import { useEquipmentIncidents } from "@/lib/query/hooks";

const INCIDENT_VIEWS = ["open", "resolved"] as const;
type IncidentView = (typeof INCIDENT_VIEWS)[number];

const VIEW_LABELS: Record<IncidentView, string> = { open: "Open", resolved: "Resolved & Closed" };
const VIEW_STATUSES: Record<IncidentView, EquipmentIncidentStatus[]> = {
  open: ["open", "acknowledged", "action_in_progress"],
  resolved: ["resolved", "closed"],
};

/** UX-OPS-001B §8.1: a durable work queue/list-detail workspace -- open/
 * active work is the default, resolved/closed history is secondary. One
 * bounded read per view (unchanged from the prior tab implementation),
 * never a single unfiltered farm-wide fetch split client-side. */
export default function EquipmentIncidentsPage() {
  const { farmId } = useParams<{ farmId: string }>();
  const { view, selected, setView, setSelected } = useViewState<IncidentView>({
    views: INCIDENT_VIEWS, defaultView: "open",
  });

  const query = useEquipmentIncidents(farmId, { status: VIEW_STATUSES[view] });
  const rows = query.data ?? [];
  const selectedIncident = rows.find((i) => i.id === selected) ?? null;

  const viewTabs: ViewTabItem<IncidentView>[] = INCIDENT_VIEWS.map((v) => ({
    value: v, label: VIEW_LABELS[v], count: query.isLoading || query.error ? undefined : (v === view ? rows.length : undefined),
  }));

  return (
    <div>
      <PageHeader
        title="Equipment Incidents"
        compact
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

      <div className="mb-4">
        <ViewTabs items={viewTabs} active={view} onChange={setView} />
      </div>

      {query.isLoading && <LoadingSkeleton rows={4} label="Loading equipment incidents" />}
      {!query.isLoading && Boolean(query.error) && <ErrorState error={query.error} onRetry={() => query.refetch()} />}
      {!query.isLoading && !query.error && rows.length === 0 && (
        <EmptyState title="Nothing here" description="No Equipment Incidents in this view." />
      )}
      {!query.isLoading && !query.error && rows.length > 0 && (
        <SplitWorkspace
          main={
            <BoundedDataRegion label={`${VIEW_LABELS[view]} incidents`}>
              <QueueList label={`${VIEW_LABELS[view]} incidents`}>
                {rows.map((incident) => (
                  <QueueRow
                    key={incident.id}
                    isSelected={incident.id === selected}
                    onSelect={() => setSelected(incident.id)}
                    title={incident.code}
                    context={incident.asset ? `${incident.asset.name} (${incident.asset.code})` : undefined}
                    status={
                      <div className="flex flex-col items-end gap-1">
                        <StatusBadge label={humanizeEnumCode(incident.status)} tone={INCIDENT_STATUS_TONE[incident.status]} />
                        <StatusBadge label={humanizeEnumCode(incident.severity)} tone={INCIDENT_SEVERITY_TONE[incident.severity]} />
                      </div>
                    }
                    meta={new Date(incident.opened_at).toLocaleDateString()}
                  />
                ))}
              </QueueList>
            </BoundedDataRegion>
          }
          rail={
            selectedIncident ? (
              <EquipmentIncidentInspector incident={selectedIncident} farmId={farmId} onClose={() => setSelected(null)} />
            ) : (
              <InspectorEmptyState />
            )
          }
        />
      )}
    </div>
  );
}
