import type { LabelSize } from "@/components/labels/LabelCard";
import type { ScanContext } from "@/lib/api/client";

/** PILOT-SCAN-001: label content derived per entity type, for the generic
 * "Print Label" / reprint route (`/farms/[farmId]/labels/[entityType]/
 * [entityId]`). Permanent identities (Carrier/Asset/Location) never
 * surface a mutable fact here (current Batch/location/status) -- only
 * their own stable code/name; the scan page (`/q/[token]`) is where those
 * resolve dynamically. Operational identities (Batch/placement/lots) may
 * show stable creation metadata (crop/variety), never current
 * stage/status.
 *
 * PILOT-SCAN-001B: extracted out of `LabelPreviewClient.tsx` (unchanged)
 * so it can also be unit-tested and reused independently of that route;
 * this is the "Permanent Carrier Label" / generic-entity content builder.
 * Stage-aware "Operational Placement Label" content (which DOES show a
 * current batch/stage/location snapshot taken at print time) is a
 * separate, deliberately distinct builder -- see `operationalLabel.ts`. */
export function labelContentFor(
  ctx: ScanContext,
): { size: LabelSize; entityTypeLabel: string; code: string; secondaryLine?: string } {
  switch (ctx.entity_type) {
    case "carrier":
      return { size: "small", entityTypeLabel: "Carrier", code: ctx.code, secondaryLine: ctx.carrier_type_name };
    case "asset":
      return { size: "small", entityTypeLabel: "Asset", code: ctx.code, secondaryLine: ctx.asset_type_name };
    case "location":
      return { size: "small", entityTypeLabel: "Location", code: ctx.location.path_string };
    case "crop_batch":
      return {
        size: "standard",
        entityTypeLabel: "Batch",
        code: ctx.code,
        secondaryLine: ctx.variety ? `${ctx.crop.common_name} · ${ctx.variety.name}` : ctx.crop.common_name,
      };
    case "batch_carrier_assignment":
      return {
        size: "standard",
        entityTypeLabel: "Placement",
        code: ctx.code,
        secondaryLine: ctx.batch.variety
          ? `${ctx.batch.crop.common_name} · ${ctx.batch.variety.name}`
          : ctx.batch.crop.common_name,
      };
    case "harvested_produce_lot":
      return {
        size: "standard",
        entityTypeLabel: "Harvest Lot",
        code: ctx.code,
        secondaryLine: ctx.batch.variety
          ? `${ctx.batch.crop.common_name} · ${ctx.batch.variety.name}`
          : ctx.batch.crop.common_name,
      };
    case "graded_produce_lot":
      return {
        size: "standard",
        entityTypeLabel: "Graded Lot",
        code: ctx.code,
        secondaryLine: ctx.variety ? `${ctx.crop.common_name} · ${ctx.variety.name}` : ctx.crop.common_name,
      };
    case "finished_goods_lot":
      return {
        size: "standard",
        entityTypeLabel: "Finished Goods Lot",
        code: ctx.code,
        secondaryLine: ctx.variety ? `${ctx.crop.common_name} · ${ctx.variety.name}` : ctx.crop.common_name,
      };
  }
}
