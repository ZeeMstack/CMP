import type {
  CropIssueRead,
  EquipmentAttentionItem,
  FarmProtocolDueSummaryItem,
  FarmWorkItemRead,
  HarvestablePlateRead,
  BatchOperationalContext,
  WaterAttentionItem,
} from "@/lib/api/client";
import { humanizeEnumCode } from "@/lib/format/humanize";

/**
 * Pure Home unified-queue aggregation, extracted so it can be unit-tested
 * without mounting Next.js routing (mirrors `workItemBoard.ts`/
 * `homeKpis.ts`'s established pattern). Builds each durable view
 * (mine/ready/attention/carryover) as a list of SEGMENTS -- one per
 * underlying source -- rather than one flat list, so a single failed
 * source can render its own inline unavailable row while every other
 * segment stays usable (CLAUDE.md "Empty/Error/Loading truth", ticket
 * §5.4). No new backend read is introduced here: every segment is built
 * from an already-fetched `useQuery` result the page already has.
 */

export type HomeQueueSourceLabel = "Crop" | "Water" | "Equipment" | "Work Item";

export type HomeQueueItemData =
  | { kind: "work_item"; item: FarmWorkItemRead }
  | { kind: "harvestable_plate"; item: HarvestablePlateRead }
  | { kind: "quality_hold_batch"; item: BatchOperationalContext }
  | { kind: "crop_issue"; item: CropIssueRead }
  | { kind: "inspection_due"; item: FarmProtocolDueSummaryItem }
  | { kind: "water_attention"; item: WaterAttentionItem }
  | { kind: "equipment_attention"; item: EquipmentAttentionItem };

export interface HomeQueueRow {
  /** Source-qualified, collision-safe across every segment/view. */
  id: string;
  sourceLabel: HomeQueueSourceLabel;
  title: string;
  context?: string;
  meta?: string;
  data: HomeQueueItemData;
}

export interface HomeQueueSegment {
  key: string;
  sourceLabel: HomeQueueSourceLabel;
  segmentLabel: string;
  isLoading: boolean;
  error: unknown;
  emptyLabel: string;
  rows: HomeQueueRow[];
}

interface QuerySource<T> {
  data: T | undefined;
  isLoading: boolean;
  error: unknown;
}

export interface HomeQueueSources {
  myWorkItems: QuerySource<FarmWorkItemRead[]>;
  harvestablePlates: QuerySource<HarvestablePlateRead[]>;
  activeBatches: QuerySource<BatchOperationalContext[]>;
  cropIssues: QuerySource<CropIssueRead[]>;
  inspectionsDue: QuerySource<FarmProtocolDueSummaryItem[]>;
  waterAttention: QuerySource<WaterAttentionItem[]>;
  equipmentAttention: QuerySource<EquipmentAttentionItem[]>;
  blockedWorkItems: QuerySource<FarmWorkItemRead[]>;
  carryoverWorkItems: QuerySource<FarmWorkItemRead[]>;
}

export function segmentForMine(sources: HomeQueueSources): HomeQueueSegment[] {
  const { myWorkItems } = sources;
  return [
    {
      key: "mine-work-items",
      sourceLabel: "Work Item",
      segmentLabel: "Assigned to me",
      isLoading: myWorkItems.isLoading,
      error: myWorkItems.error,
      emptyLabel: "Nothing assigned to you right now.",
      rows: (myWorkItems.data ?? []).map((item) => ({
        id: `work-item:${item.id}`,
        sourceLabel: "Work Item",
        title: item.title,
        context: item.crop_batch ? `Batch ${item.crop_batch.code}` : item.location ? item.location.code : undefined,
        meta: item.due_at ? new Date(item.due_at).toLocaleDateString() : undefined,
        data: { kind: "work_item", item },
      })),
    },
  ];
}

export function segmentForReady(sources: HomeQueueSources): HomeQueueSegment[] {
  const { harvestablePlates } = sources;
  return [
    {
      key: "ready-harvest",
      sourceLabel: "Crop",
      segmentLabel: "Ready to harvest",
      isLoading: harvestablePlates.isLoading,
      error: harvestablePlates.error,
      emptyLabel: "Nothing ready to harvest right now.",
      rows: (harvestablePlates.data ?? []).map((plate) => ({
        id: `harvestable:${plate.production_plate_id}`,
        sourceLabel: "Crop",
        title: `${plate.crop_common_name} · Batch ${plate.batch_code}`,
        context: plate.production_plate_code,
        meta: plate.location?.grow_table?.code,
        data: { kind: "harvestable_plate", item: plate },
      })),
    },
  ];
}

export function segmentForAttention(sources: HomeQueueSources): HomeQueueSegment[] {
  const { activeBatches, cropIssues, inspectionsDue, waterAttention, equipmentAttention, blockedWorkItems } = sources;

  const holdBatches = (activeBatches.data ?? []).filter((b) => b.open_quality_hold_count > 0);
  const openIssues = (cropIssues.data ?? []).filter((i) => i.status === "open");

  return [
    {
      key: "attention-quality-holds",
      sourceLabel: "Crop",
      segmentLabel: "Quality holds",
      isLoading: activeBatches.isLoading,
      error: activeBatches.error,
      emptyLabel: "No open quality holds right now.",
      rows: holdBatches.map((b) => ({
        id: `quality-hold:${b.id}`,
        sourceLabel: "Crop",
        title: `Batch ${b.code}`,
        context: `${b.open_quality_hold_count} open quality hold${b.open_quality_hold_count === 1 ? "" : "s"}`,
        data: { kind: "quality_hold_batch", item: b },
      })),
    },
    {
      key: "attention-crop-issues",
      sourceLabel: "Crop",
      segmentLabel: "Crop attention",
      isLoading: cropIssues.isLoading,
      error: cropIssues.error,
      emptyLabel: "No open crop issues right now.",
      rows: openIssues.map((issue) => ({
        id: `crop-issue:${issue.id}`,
        sourceLabel: "Crop",
        title: issue.code,
        context: `${humanizeEnumCode(issue.category)} · ${humanizeEnumCode(issue.severity)}${issue.is_follow_up_overdue ? " · follow-up overdue" : ""}`,
        data: { kind: "crop_issue", item: issue },
      })),
    },
    {
      key: "attention-inspections-due",
      sourceLabel: "Crop",
      segmentLabel: "Inspections due",
      isLoading: inspectionsDue.isLoading,
      error: inspectionsDue.error,
      emptyLabel: "No inspections due right now.",
      rows: (inspectionsDue.data ?? []).map((row) => ({
        id: `inspection-due:${row.batch_id}`,
        sourceLabel: "Crop",
        title: `Batch ${row.batch_code}`,
        context: row.protocol?.name,
        meta: row.overdue_count > 0 ? `${row.overdue_count} overdue` : `${row.due_count} due`,
        data: { kind: "inspection_due", item: row },
      })),
    },
    {
      key: "attention-water",
      sourceLabel: "Water",
      segmentLabel: "Water attention",
      isLoading: waterAttention.isLoading,
      error: waterAttention.error,
      emptyLabel: "Nothing currently needs Water attention.",
      rows: (waterAttention.data ?? []).map((item, i) => ({
        id: `water-attention:${item.kind}:${i}`,
        sourceLabel: "Water",
        title: item.message,
        data: { kind: "water_attention", item },
      })),
    },
    {
      key: "attention-equipment",
      sourceLabel: "Equipment",
      segmentLabel: "Equipment attention",
      isLoading: equipmentAttention.isLoading,
      error: equipmentAttention.error,
      emptyLabel: "Nothing currently needs Equipment attention.",
      rows: (equipmentAttention.data ?? []).map((item, i) => ({
        id: `equipment-attention:${item.kind}:${i}`,
        sourceLabel: "Equipment",
        title: item.message,
        data: { kind: "equipment_attention", item },
      })),
    },
    {
      key: "attention-blocked-work-items",
      sourceLabel: "Work Item",
      segmentLabel: "Blocked work",
      isLoading: blockedWorkItems.isLoading,
      error: blockedWorkItems.error,
      emptyLabel: "No blocked work items right now.",
      rows: (blockedWorkItems.data ?? []).map((item) => ({
        id: `work-item:${item.id}`,
        sourceLabel: "Work Item",
        title: item.title,
        context: item.blocked_reason ?? undefined,
        data: { kind: "work_item", item },
      })),
    },
  ];
}

export function segmentForCarryover(sources: HomeQueueSources): HomeQueueSegment[] {
  const { carryoverWorkItems } = sources;
  return [
    {
      key: "carryover-work-items",
      sourceLabel: "Work Item",
      segmentLabel: "Carryover",
      isLoading: carryoverWorkItems.isLoading,
      error: carryoverWorkItems.error,
      emptyLabel: "Nothing carried over.",
      rows: (carryoverWorkItems.data ?? []).map((item) => ({
        id: `work-item:${item.id}`,
        sourceLabel: "Work Item",
        title: item.title,
        context: item.crop_batch ? `Batch ${item.crop_batch.code}` : undefined,
        meta: item.due_at ? new Date(item.due_at).toLocaleDateString() : undefined,
        data: { kind: "work_item", item },
      })),
    },
  ];
}

/** A view's count badge is shown only when every one of its segments has
 * successfully loaded -- never a partial sum while a source is still
 * loading, and never displayed at all when a source has failed (a failed
 * source's true count is unknown, so showing any number -- including the
 * other segments' sum alone -- could be misread as complete). */
export function segmentsTotalCount(segments: HomeQueueSegment[]): number | undefined {
  if (segments.some((s) => s.isLoading || s.error)) return undefined;
  return segments.reduce((sum, s) => sum + s.rows.length, 0);
}
