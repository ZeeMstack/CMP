import type { LabelSize } from "@/components/labels/LabelCard";

/** PILOT-SCAN-001B: `OperationalLabelContext` -- the one small,
 * presentation-only shape every stage-label builder below returns. Never
 * a new source of domain truth: every field passed into these builders
 * must already come from an already-authoritative read (a just-succeeded
 * command's own response), never invented/guessed/re-derived. This module
 * is deliberately QR-entity-agnostic -- it only formats what gets
 * PRINTED; which QR entity type/id backs a label is decided by each
 * calling page (see `docs/domain/QR_SCAN_MODEL.md`'s per-stage table).
 *
 * Distinguishes, per `docs/domain/QR_SCAN_MODEL.md`'s frozen terms and
 * the FINAL CLOSURE entity-selection rule (no implicit fallback between
 * these three meanings):
 *  - Batch Master Label: identifies the biological Batch itself
 *    (QR entity_type "crop_batch"). One per Batch, never one per tray.
 *  - Permanent Carrier Label: identifies a reusable Carrier's own
 *    physical identity (QR entity_type "carrier"), independent of which
 *    Batch it currently holds -- PILOT-SCAN-001's original generic label.
 *  - Operational Placement Label: identifies ONE specific physical
 *    carrier/placement (a Seed Tray, Nursery/Production Cultivation
 *    Plate, Grow Cube, or Grow Bag) together with a PRINT-TIME SNAPSHOT
 *    of the batch/stage/location context it currently holds. Its QR is
 *    ALWAYS the stable Batch-placement identity (entity_type
 *    "batch_carrier_assignment"), never the reusable Carrier's own
 *    identity -- a Carrier can later hold a different Batch, and a
 *    placement label must keep resolving THIS placement for its whole
 *    physical life, never silently become the new occupant's label. If
 *    no stable placement id is available (Germination placement is the
 *    one stage where this can genuinely happen -- see
 *    `germination/page.tsx`'s `GerminationReceiptCard`), NO Operational
 *    Placement Label is built at all; there is no Carrier-QR fallback.
 *  - Both label kinds use the STANDARD (100x60mm) template -- per
 *    `LabelCard.tsx`'s own existing size rationale, "standard" is for
 *    "operational identity, more identifying text to fit"; a stage label
 *    with a batch code plus location breakdown needs that room. SMALL
 *    (50x30mm) stays reserved for the bare, no-context Permanent Carrier/
 *    Asset/Location label PILOT-SCAN-001 already built.
 */
export interface OperationalLabelContext {
  size: LabelSize;
  entityTypeLabel: string;
  code: string;
  /** 1-4 short supporting lines, printed stacked beneath the code. Never
   * a raw UUID; never a value not already present on the triggering
   * command's own result. */
  lines: string[];
}

function batchLine(batchCode: string): string {
  return `Batch ${batchCode}`;
}

/** Batch Master Label -- printed once per Batch (Sowing success), never
 * per tray/plate: a Batch may occupy several carriers/locations at once,
 * so this alone must never stand in for any single physical placement. */
export function batchMasterLabel(params: { batchCode: string; cropAndVariety?: string }): OperationalLabelContext {
  return {
    size: "standard",
    entityTypeLabel: "Batch",
    code: params.batchCode,
    lines: params.cropAndVariety ? [params.cropAndVariety] : [],
  };
}

/** Operational Placement Label for a Sowing Seed Tray. */
export function sowingTrayLabel(params: { batchCode: string; trayCode: string }): OperationalLabelContext {
  return {
    size: "standard",
    entityTypeLabel: "Seed Tray",
    code: params.trayCode,
    lines: [batchLine(params.batchCode), "Sowing"],
  };
}

/** Operational Placement Label for a Germination tray placement.
 * Chamber/Trolley/Level are Asset/AssetPosition facts (never modeled as
 * Location) -- shown here exactly as the placement command already
 * returned them, never re-derived as a Location path. */
export function germinationPlacementLabel(params: {
  batchCode: string;
  trayCode: string;
  chamberCode: string;
  trolleyCode: string;
  positionCode: string;
}): OperationalLabelContext {
  return {
    size: "standard",
    entityTypeLabel: "Seed Tray",
    code: params.trayCode,
    lines: [
      batchLine(params.batchCode),
      "Germination",
      `Chamber ${params.chamberCode} / Trolley ${params.trolleyCode} / Level ${params.positionCode}`,
    ],
  };
}

/** Operational Placement Label for a Seedling-stage tray (still the same
 * physical Seed Tray -- Seedling entry does not swap carriers). */
export function seedlingEntryLabel(params: {
  batchCode: string;
  trayCode: string;
  tableCode: string;
}): OperationalLabelContext {
  return {
    size: "standard",
    entityTypeLabel: "Seed Tray",
    code: params.trayCode,
    lines: [batchLine(params.batchCode), "Seedling", params.tableCode],
  };
}

/** Operational Placement Label for an InterSalads destination Nursery
 * Cultivation Plate. */
export function intersaladsPlacementLabel(params: {
  batchCode: string;
  carrierCode: string;
  tableCode: string;
}): OperationalLabelContext {
  return {
    size: "standard",
    entityTypeLabel: "Nursery Cultivation Plate",
    code: params.carrierCode,
    lines: [batchLine(params.batchCode), "InterSalads", params.tableCode],
  };
}

/** Operational Placement Label for a Leafy Production destination
 * Production Cultivation Plate. The destination carrier is ALWAYS the
 * Production Cultivation Plate the transfer command created/assigned --
 * never the source Nursery Cultivation Plate, which does not move into
 * Production. */
export function leafyProductionPlacementLabel(params: {
  batchCode: string;
  carrierCode: string;
  tableCode: string;
}): OperationalLabelContext {
  return {
    size: "standard",
    entityTypeLabel: "Production Cultivation Plate",
    code: params.carrierCode,
    lines: [batchLine(params.batchCode), "Leafy Production", params.tableCode],
  };
}

/** Operational Placement Label for an InterVines destination Grow Cube.
 * Never shows a Grow Bag -- Grow Bags do not exist until Vines
 * Production. */
export function intervinesPlacementLabel(params: {
  batchCode: string;
  carrierCode: string;
  tableCode: string;
}): OperationalLabelContext {
  return {
    size: "standard",
    entityTypeLabel: "Grow Cube",
    code: params.carrierCode,
    lines: [batchLine(params.batchCode), "InterVines", params.tableCode],
  };
}

/** Operational Placement Label for a Vines Production destination Grow
 * Bag. `gutterCode` is the only destination-location fact currently
 * exposed by `VinesProductionTransferRead` (no Greenhouse/Zone/Span
 * breakdown) -- see `docs/product/OPEN_QUESTIONS.md` for that gap. */
export function vinesProductionPlacementLabel(params: {
  batchCode: string;
  carrierCode: string;
  gutterCode: string;
  plantCount: number;
}): OperationalLabelContext {
  return {
    size: "standard",
    entityTypeLabel: "Grow Bag",
    code: params.carrierCode,
    lines: [batchLine(params.batchCode), "Vines Production", params.gutterCode, `${params.plantCount} plants`],
  };
}
