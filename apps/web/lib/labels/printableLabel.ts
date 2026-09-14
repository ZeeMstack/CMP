import type { LabelSize } from "@/components/labels/LabelCard";
import { LABEL_TEMPLATE_VERSION } from "@/components/labels/LabelCard";
import { printQrLabel, type QrEntityType } from "@/lib/api/client";

/** PILOT-SCAN-001B: the one small, serializable, presentation-only shape
 * every "Print Label(s)" action in the app builds and hands to the
 * label-only print route (`/print/labels`). Never a new source of domain
 * truth -- every field here is copied from an already-authoritative read
 * (a completed command's own result, or a resolved `ScanContext`), never
 * invented/guessed. Plain strings only (no ReactNode) so a list of these
 * survives a JSON round-trip through a URL query param. */
export interface PrintableLabel {
  token: string;
  size: LabelSize;
  /** PILOT-SCAN-001B FINAL CLOSURE: which QR entity this token actually
   * identifies -- `"batch_carrier_assignment"` for a stable placement
   * identity, `"carrier"` for a bounded fallback, `"crop_batch"` for a
   * Batch Master Label, etc. Needed to build the exact same
   * `template = "{entity_type}_{size}"` string `LabelPreviewClient.tsx`
   * already uses when calling the print-request audit API (`requestPrintAudit`
   * below) -- never a second, invented entity-type encoding. */
  entityType: QrEntityType;
  /** e.g. "Batch", "Seed Tray", "Nursery Cultivation Plate", "Grow Cube". */
  entityTypeLabel: string;
  /** The one prominent human code (Batch code, Carrier code, Lot code). */
  code: string;
  /** 0-3 short supporting lines, printed stacked beneath the code --
   * e.g. ["Batch B-LET-2026-014", "Germination", "GH-03 / GERM-01 / GT-02 / L03"].
   * Never a raw UUID. */
  lines: string[];
}

const QUERY_PARAM = "items";

/** `/print/labels?items=<url-encoded JSON array of PrintableLabel>`.
 * Adequate for this pilot's realistic batch sizes (a handful of trays per
 * operation, per CLAUDE.md's own "minimize floor typing/scans" scope, not
 * an arbitrary bulk export) -- see PILOT-SCAN-001B's own "no complex label
 * queues" instruction. */
export function buildPrintLabelsUrl(labels: PrintableLabel[]): string {
  const encoded = encodeURIComponent(JSON.stringify(labels));
  return `/print/labels?${QUERY_PARAM}=${encoded}`;
}

export function parsePrintLabelsFromSearchParams(searchParams: URLSearchParams): PrintableLabel[] {
  const raw = searchParams.get(QUERY_PARAM);
  if (!raw) return [];
  try {
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(
      (item): item is PrintableLabel =>
        typeof item === "object" &&
        item !== null &&
        typeof (item as PrintableLabel).token === "string" &&
        typeof (item as PrintableLabel).code === "string" &&
        typeof (item as PrintableLabel).entityType === "string",
    );
  } catch {
    return [];
  }
}

/** Opens the label-only print document in a new tab, synchronously (within
 * the same click-event call stack as the caller) so browsers never treat
 * it as an unrequested popup. Never blocks on -- or is blocked by -- the
 * separate `qr_label_print_requested` audit call a caller may also fire;
 * PILOT-SCAN-001B: printing must never gate/repeat/reverse the farm
 * operation that already succeeded. */
export function openLabelPrintWindow(labels: PrintableLabel[]): void {
  if (labels.length === 0) return;
  window.open(buildPrintLabelsUrl(labels), "_blank", "noopener,noreferrer");
}

/** PILOT-SCAN-001B FINAL CLOSURE: records one `qr_label_print_requested`
 * audit event PER label via the existing PILOT-SCAN-001 `POST
 * /qr/{token}/print` API -- the exact same audit primitive
 * `LabelPreviewClient.tsx`'s own single-label "Print label" button already
 * uses, never a new/generic page-level audit event. One "Print Tray Labels
 * (5)" click therefore produces five independent, entity-specific audit
 * records, not one.
 *
 * Deliberately NOT awaited by callers, and deliberately called AFTER
 * `openLabelPrintWindow` (never before/instead of it): the print window
 * must open synchronously within the click handler for popup-blocker
 * safety, and a failed/slow audit call must never gate, delay, or reverse
 * the print action that already happened -- matching this ticket's own
 * "a failed print must never affect the already-successful farm operation"
 * rule, extended here to "a failed audit call must never affect the
 * already-opened print window" (`.catch` below swallows any error rather
 * than surfacing it as a print failure).
 *
 * `reason: null` is correct for every one of this function's own callers:
 * each label here was generated in the SAME operation that is now printing
 * it for the first time, so the backend's own reprint bookkeping
 * (`is_reprint`, derived server-side from whether a prior print request
 * already exists for that QR identity) will read `false` and never demand
 * a reason. A genuine reprint of one of these placements later goes
 * through the existing per-entity reprint UI (`LabelPreviewClient.tsx`),
 * which already collects and forwards an operator-entered reason. */
export function requestPrintAudit(labels: PrintableLabel[]): void {
  for (const label of labels) {
    printQrLabel(label.token, {
      template: `${label.entityType}_${label.size}`,
      template_version: LABEL_TEMPLATE_VERSION,
      reason: null,
    }).catch(() => {
      // Intentionally swallowed -- see doc comment above.
    });
  }
}

/** The one call every stage-label "Print Labels"/"Print Batch Label"/
 * "Print Tray Labels" button in the app should make: opens the print
 * document (synchronously, popup-blocker-safe), then fires this job's
 * per-label print-request audits. Kept as one function so no call site can
 * accidentally open the window without also recording the audit (or vice
 * versa). NOT used by `LabelPreviewClient.tsx`'s own single-label reprint
 * button, which already performs its own explicit, reason-collecting
 * `POST /qr/{token}/print` call before opening the window -- calling this
 * too there would double-record the same print request. */
export function printLabels(labels: PrintableLabel[]): void {
  openLabelPrintWindow(labels);
  requestPrintAudit(labels);
}
