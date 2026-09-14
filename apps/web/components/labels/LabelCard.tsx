import type { ReactNode } from "react";

import { QrCodeSvg } from "@/components/labels/QrCodeSvg";

/** PILOT-SCAN-001 fixed, versioned label templates -- not a WYSIWYG
 * designer. Two sizes only, per the pilot's own scope:
 *  - "small"    50mm x 30mm  -- Carriers/Assets/Locations (permanent
 *               physical identity; the physical object itself is small).
 *  - "standard" 100mm x 60mm -- Batch/placement/lot labels (operational
 *               identity, more identifying text to fit).
 * Both are common thermal-label stock sizes. Dimensions are asserted in
 * CSS mm units so `window.print()` reproduces them physically as-is on a
 * printer configured for that stock. */
export type LabelSize = "small" | "standard";
export const LABEL_TEMPLATE_VERSION = "v1";

const DIMENSIONS: Record<LabelSize, { widthMm: number; heightMm: number; qrMm: number }> = {
  small: { widthMm: 50, heightMm: 30, qrMm: 20 },
  standard: { widthMm: 100, heightMm: 60, qrMm: 32 },
};

export function LabelCard({
  size,
  entityTypeLabel,
  code,
  secondaryLine,
  token,
  canonicalAppOrigin,
}: {
  size: LabelSize;
  entityTypeLabel: string;
  code: string;
  secondaryLine?: ReactNode;
  token: string;
  canonicalAppOrigin: string;
}) {
  const { widthMm, heightMm, qrMm } = DIMENSIONS[size];
  return (
    <div
      className="label-card flex items-center justify-between gap-2 overflow-hidden border border-wl-border bg-white p-2 text-black print:border-none"
      style={{ width: `${widthMm}mm`, height: `${heightMm}mm` }}
    >
      <div className="flex min-w-0 flex-1 flex-col justify-between gap-1">
        <div className="text-[7px] font-semibold uppercase tracking-wide text-neutral-500">growCMP</div>
        <div className="min-w-0">
          <div className="text-[7px] font-semibold uppercase tracking-wide text-neutral-600">{entityTypeLabel}</div>
          <div className="truncate font-mono text-[13px] font-bold leading-tight text-black">{code}</div>
          {secondaryLine && <div className="truncate text-[8px] text-neutral-700">{secondaryLine}</div>}
        </div>
      </div>
      <div className="flex-shrink-0">
        <QrCodeSvg canonicalAppOrigin={canonicalAppOrigin} token={token} sizeMm={qrMm} />
      </div>
    </div>
  );
}

/** Wraps a `LabelCard` (or several, for batch printing) in the print-only
 * page-size rule so `window.print()` produces one label per physical
 * label, no browser header/footer chrome. Screen preview shows a plain
 * white card; only `@media print` fixes the physical page size. */
export function LabelPrintSheet({ size, children }: { size: LabelSize; children: ReactNode }) {
  const { widthMm, heightMm } = DIMENSIONS[size];
  return (
    <>
      <style>{`
        @media print {
          @page { size: ${widthMm}mm ${heightMm}mm; margin: 0; }
          body { margin: 0; }
          .label-print-sheet { break-after: page; }
        }
      `}</style>
      <div className="label-print-sheet flex flex-wrap gap-4 print:gap-0">{children}</div>
    </>
  );
}
