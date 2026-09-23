import Link from "next/link";

import { InspectorEmptyState, InspectorShell } from "@/components/layout/InspectorShell";
import { WorkItemRow } from "@/components/work-items/WorkItemRow";
import type { EquipmentAttentionItem } from "@/lib/api/client";
import { humanizeEnumCode } from "@/lib/format/humanize";
import type { HomeQueueRow } from "@/lib/format/homeQueue";

/** Today on the Farm's "Equipment Attention" deep-link -- kept identical to
 * the pre-UX-OPS-001B page.tsx helper of the same name/behavior. */
export function equipmentAttentionHref(farmId: string, item: EquipmentAttentionItem): string {
  if (item.kind === "OPEN_INCIDENT") {
    return `/farms/${farmId}/equipment-incidents/${item.equipment_incident_id}`;
  }
  const entityType = item.asset_id ? "asset" : "carrier";
  const entityId = item.asset_id ?? item.carrier_id;
  return `/farms/${farmId}/equipment/${entityType}/${entityId}/readiness`;
}

const linkClass = "inline-block text-sm font-medium text-wl-brand hover:underline";
const factsClass = "flex flex-col gap-1.5 text-sm text-wl-text";

/** Selected-item inspector/action rail for the Home unified queue. Renders
 * by `row.data.kind` -- a Farm Work Item reuses the existing `WorkItemRow`
 * action cell verbatim (same commands/payloads/permissions), every other
 * source shows its own already-authoritative facts plus a link into the
 * approved dedicated route for that action (ticket §5.2: "unless the
 * approved action already requires a dedicated route"). Never fabricates a
 * fact the source query doesn't already provide. */
export function HomeInspector({
  row,
  farmId,
  currentUserId,
  onClose,
}: {
  row: HomeQueueRow | null;
  farmId: string;
  currentUserId?: string;
  onClose: () => void;
}) {
  if (!row) return <InspectorEmptyState />;

  const { data } = row;

  if (data.kind === "work_item") {
    return (
      <InspectorShell title={data.item.title} subtitle={data.item.code} onClose={onClose}>
        <table className="w-full text-left text-sm">
          <tbody>
            <WorkItemRow item={data.item} farmId={farmId} currentUserId={currentUserId} />
          </tbody>
        </table>
      </InspectorShell>
    );
  }

  if (data.kind === "harvestable_plate") {
    const plate = data.item;
    return (
      <InspectorShell title={`Batch ${plate.batch_code}`} subtitle={plate.crop_common_name} onClose={onClose}>
        <dl className={factsClass}>
          <div>
            <dt className="text-xs text-wl-text-secondary">Plate</dt>
            <dd>{plate.production_plate_code}</dd>
          </div>
          {plate.location?.grow_table && (
            <div>
              <dt className="text-xs text-wl-text-secondary">Location</dt>
              <dd>{plate.location.grow_table.code}</dd>
            </div>
          )}
        </dl>
        <Link className={linkClass} href={`/farms/${farmId}/leafy-production/harvest?batchId=${plate.batch_id}`}>
          Open Harvest
        </Link>
      </InspectorShell>
    );
  }

  if (data.kind === "quality_hold_batch") {
    const batch = data.item;
    return (
      <InspectorShell title={`Batch ${batch.code}`} onClose={onClose}>
        <p className="text-sm text-wl-text">
          {batch.open_quality_hold_count} open quality hold{batch.open_quality_hold_count === 1 ? "" : "s"}
        </p>
        <Link className={linkClass} href={`/farms/${farmId}/crop-batches/${batch.id}`}>
          View batch
        </Link>
      </InspectorShell>
    );
  }

  if (data.kind === "crop_issue") {
    const issue = data.item;
    return (
      <InspectorShell title={issue.code} subtitle={humanizeEnumCode(issue.category)} onClose={onClose}>
        <dl className={factsClass}>
          <div>
            <dt className="text-xs text-wl-text-secondary">Severity</dt>
            <dd>{humanizeEnumCode(issue.severity)}</dd>
          </div>
          {issue.is_follow_up_overdue && <p className="text-wl-flag-fg">Follow-up overdue</p>}
        </dl>
        <Link className={linkClass} href={`/farms/${farmId}/crop-issues/${issue.id}`}>
          Open issue
        </Link>
      </InspectorShell>
    );
  }

  if (data.kind === "inspection_due") {
    const item = data.item;
    return (
      <InspectorShell title={`Batch ${item.batch_code}`} subtitle={item.protocol?.name} onClose={onClose}>
        <p className="text-sm text-wl-text">
          {item.overdue_count > 0 ? `${item.overdue_count} overdue` : `${item.due_count} due`}
        </p>
        <Link className={linkClass} href={`/farms/${farmId}/production/inspect?batchId=${item.batch_id}`}>
          Inspect Crop
        </Link>
      </InspectorShell>
    );
  }

  if (data.kind === "water_attention") {
    const item = data.item;
    const href = item.kind === "CIRCUIT_MISSING_RESERVOIR" ? `/farms/${farmId}/water/setup` : `/farms/${farmId}/water/measurements`;
    return (
      <InspectorShell title="Water attention" onClose={onClose}>
        <p className="text-sm text-wl-text">{item.message}</p>
        <Link className={linkClass} href={href}>
          Open Water &amp; Nutrients
        </Link>
      </InspectorShell>
    );
  }

  // equipment_attention
  const item = data.item;
  return (
    <InspectorShell title="Equipment attention" onClose={onClose}>
      <p className="text-sm text-wl-text">{item.message}</p>
      <Link className={linkClass} href={equipmentAttentionHref(farmId, item)}>
        {item.kind === "OPEN_INCIDENT" ? "Open Incident" : "View Readiness"}
      </Link>
    </InspectorShell>
  );
}
