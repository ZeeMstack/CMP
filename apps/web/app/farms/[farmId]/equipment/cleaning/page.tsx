"use client";

import { useParams } from "next/navigation";

import { Breadcrumbs } from "@/components/Breadcrumbs";
import { ReadinessInspector, READINESS_STATE_TONE } from "@/components/equipment/ReadinessInspector";
import { BoundedDataRegion } from "@/components/layout/BoundedDataRegion";
import { InspectorEmptyState } from "@/components/layout/InspectorShell";
import { QueueList, QueueRow } from "@/components/layout/QueueRow";
import { SplitWorkspace } from "@/components/layout/SplitWorkspace";
import { ViewTabs, type ViewTabItem } from "@/components/layout/ViewTabs";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { LoadingSkeleton } from "@/components/LoadingSkeleton";
import { PageHeader } from "@/components/PageHeader";
import { StatusBadge } from "@/components/StatusBadge";
import type { EquipmentReadinessCurrentState } from "@/lib/api/client";
import { humanizeEnumCode } from "@/lib/format/humanize";
import { useViewState } from "@/lib/navigation/useViewState";
import { useEquipmentReadinessList } from "@/lib/query/hooks";

const READINESS_VIEWS = ["unassessed", "cleaning", "release", "attention"] as const;
type ReadinessView = (typeof READINESS_VIEWS)[number];

const VIEW_LABELS: Record<ReadinessView, string> = {
  unassessed: "Unassessed",
  cleaning: "Cleaning",
  release: "Awaiting release",
  attention: "Attention",
};

const VIEW_STATES: Record<ReadinessView, EquipmentReadinessCurrentState[]> = {
  unassessed: ["unknown"],
  cleaning: ["awaiting_cleaning"],
  release: ["cleaning_completed"],
  attention: ["damaged", "maintenance"],
};

const VIEW_EMPTY_LABEL: Record<ReadinessView, string> = {
  unassessed: "Nothing awaiting an initial assessment.",
  cleaning: "Nothing awaiting cleaning.",
  release: "Nothing awaiting release to Ready.",
  attention: "Nothing currently damaged or in maintenance.",
};

/** UX-OPS-001B §7.3: the Readiness operations workspace -- URL-backed
 * durable views over the real lifecycle states (never a fabricated
 * "ready"/empty reading; UNKNOWN and CLEANING_COMPLETED are frozen-rule
 * distinct from READY). RETIRED is deliberately not one of these queues
 * (terminal, not actionable work) -- reachable only via a specific
 * entity's own Readiness detail/history. */
export default function EquipmentCleaningQueuePage() {
  const { farmId } = useParams<{ farmId: string }>();
  const { view, selected, setView, setSelected } = useViewState<ReadinessView>({
    views: READINESS_VIEWS,
    defaultView: "unassessed",
  });

  const query = useEquipmentReadinessList(farmId, VIEW_STATES[view]);
  const rows = query.data ?? [];
  const selectedState = rows.find((r) => r.id === selected) ?? null;

  const viewTabs: ViewTabItem<ReadinessView>[] = READINESS_VIEWS.map((v) => ({ value: v, label: VIEW_LABELS[v] }));

  return (
    <div>
      <PageHeader
        title="Equipment Readiness"
        description="Equipment lifecycle work: initial assessment, cleaning, release to Ready, and damage/maintenance attention."
        compact
        breadcrumbs={
          <Breadcrumbs items={[{ label: "Home", href: `/farms/${farmId}` }, { label: "Equipment Readiness" }]} />
        }
      />

      <div className="mb-4">
        <ViewTabs items={viewTabs} active={view} onChange={setView} />
      </div>

      {query.isLoading && <LoadingSkeleton rows={4} label={`Loading ${VIEW_LABELS[view].toLowerCase()}`} />}
      {!query.isLoading && Boolean(query.error) && <ErrorState error={query.error} onRetry={() => query.refetch()} />}
      {!query.isLoading && !query.error && rows.length === 0 && (
        <EmptyState title={VIEW_EMPTY_LABEL[view]} description="Nothing to do in this view right now." />
      )}
      {!query.isLoading && !query.error && rows.length > 0 && (
        <SplitWorkspace
          main={
            <BoundedDataRegion label={`${VIEW_LABELS[view]} queue`}>
              <QueueList label={`${VIEW_LABELS[view]} queue`}>
                {rows.map((row) => (
                  <QueueRow
                    key={row.id}
                    isSelected={row.id === selected}
                    onSelect={() => setSelected(row.id)}
                    title={row.entity_code}
                    context={row.equipment_type_name}
                    status={<StatusBadge label={humanizeEnumCode(row.current_state)} tone={READINESS_STATE_TONE[row.current_state]} />}
                    meta={new Date(row.state_changed_at).toLocaleDateString()}
                  />
                ))}
              </QueueList>
            </BoundedDataRegion>
          }
          rail={
            selectedState ? (
              <ReadinessInspector state={selectedState} farmId={farmId} onClose={() => setSelected(null)} />
            ) : (
              <InspectorEmptyState />
            )
          }
        />
      )}
    </div>
  );
}
