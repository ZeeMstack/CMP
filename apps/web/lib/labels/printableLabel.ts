import type { LabelSize } from "@/components/labels/LabelCard";

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
        typeof (item as PrintableLabel).code === "string",
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
