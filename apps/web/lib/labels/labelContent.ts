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
 * separate, deliberately distinct builder -- see `operationalLabel.ts`.
 * Returns plain `lines: string[]` (never `ReactNode`) so this same content
 * feeds both the on-screen preview AND `openLabelPrintWindow`'s
 * `PrintableLabel.lines`, which must survive a JSON round-trip through a
 * URL query param -- see `printableLabel.ts`.
 *
 * PILOT-SCAN-001B FINAL CLOSURE ("Reprint Current Label"): the
 * `batch_carrier_assignment` case is the one exception to "no current
 * fact" above -- a Placement IS the current-stage identity (this ticket's
 * Operational Placement Label), so reprinting it through this same generic
 * route must show the CURRENT physical carrier and CURRENT location, freshly
 * resolved every time via `resolveQr` (never a stale snapshot from when it
 * was first printed) -- exactly what `BatchCarrierAssignmentScanContext`
 * already returns. No workflow-stage NAME is shown here (that scan context
 * carries no stage field); showing only what is authoritatively available
 * (crop/variety, carrier code, current location) rather than a guessed one. */
export function labelContentFor(
  ctx: ScanContext,
): { size: LabelSize; entityTypeLabel: string; code: string; lines: string[] } {
  switch (ctx.entity_type) {
    case "carrier":
      return { size: "small", entityTypeLabel: "Carrier", code: ctx.code, lines: [ctx.carrier_type_name] };
    case "asset":
      return { size: "small", entityTypeLabel: "Asset", code: ctx.code, lines: [ctx.asset_type_name] };
    case "location":
      return { size: "small", entityTypeLabel: "Location", code: ctx.location.path_string, lines: [] };
    case "crop_batch":
      return {
        size: "standard",
        entityTypeLabel: "Batch",
        code: ctx.code,
        lines: [ctx.variety ? `${ctx.crop.common_name} · ${ctx.variety.name}` : ctx.crop.common_name],
      };
    case "batch_carrier_assignment": {
      const cropLine = ctx.batch.variety ? `${ctx.batch.crop.common_name} · ${ctx.batch.variety.name}` : ctx.batch.crop.common_name;
      const carrierLine = `Carrier ${ctx.carrier_code}`;
      const locationLine = ctx.released
        ? "Placement released"
        : ctx.current_location
          ? ctx.current_location.path_string
          : (ctx.unresolved_reason ?? "Location unknown");
      return {
        size: "standard",
        entityTypeLabel: "Placement",
        code: ctx.code,
        lines: [cropLine, carrierLine, locationLine],
      };
    }
    case "harvested_produce_lot":
      return {
        size: "standard",
        entityTypeLabel: "Harvest Lot",
        code: ctx.code,
        lines: [ctx.batch.variety ? `${ctx.batch.crop.common_name} · ${ctx.batch.variety.name}` : ctx.batch.crop.common_name],
      };
    case "graded_produce_lot":
      return {
        size: "standard",
        entityTypeLabel: "Graded Lot",
        code: ctx.code,
        lines: [ctx.variety ? `${ctx.crop.common_name} · ${ctx.variety.name}` : ctx.crop.common_name],
      };
    case "finished_goods_lot":
      return {
        size: "standard",
        entityTypeLabel: "Finished Goods Lot",
        code: ctx.code,
        lines: [ctx.variety ? `${ctx.crop.common_name} · ${ctx.variety.name}` : ctx.crop.common_name],
      };
  }
}
