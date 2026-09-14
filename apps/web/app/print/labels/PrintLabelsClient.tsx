"use client";

import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useRef } from "react";

import { ErrorState } from "@/components/ErrorState";
import { LabelCard, labelDimensionsMm } from "@/components/labels/LabelCard";
import { AppError } from "@/lib/errors/adapter";
import { parsePrintLabelsFromSearchParams } from "@/lib/labels/printableLabel";

/** PILOT-SCAN-001B: fixed page sizes for the pilot's two label templates,
 * addressed by CSS named pages (`page: label-small` / `page: label-
 * standard`) rather than a single `@page { size }` rule -- one print job
 * may legitimately mix sizes (e.g. one STANDARD Batch Master Label
 * alongside several SMALL Tray labels from a single Sowing), and a plain
 * `@page` rule is document-global, not scoped per element -- the last one
 * declared would silently win for every page. Named pages let each
 * label's own wrapper select its physical page size independently. */
function PrintStyles() {
  const small = labelDimensionsMm("small");
  const standard = labelDimensionsMm("standard");
  return (
    <style>{`
      @media print {
        @page label-small { size: ${small.widthMm}mm ${small.heightMm}mm; margin: 0; }
        @page label-standard { size: ${standard.widthMm}mm ${standard.heightMm}mm; margin: 0; }
        body { margin: 0; }
      }
      .print-label-item { break-after: page; }
      .print-label-item.size-small { page: label-small; }
      .print-label-item.size-standard { page: label-standard; }
    `}</style>
  );
}

function PrintLabelsBody({ canonicalAppOrigin }: { canonicalAppOrigin: string | null }) {
  const searchParams = useSearchParams();
  const labels = parsePrintLabelsFromSearchParams(searchParams);
  const hasTriggeredPrint = useRef(false);

  useEffect(() => {
    // PILOT-SCAN-001B: the browser print dialog only opens on this
    // explicit trigger, once, after the labels are already rendered --
    // never silent/automatic printing of anything the operator did not
    // just click "Print Labels" for. This route is only ever reached from
    // that click (`openLabelPrintWindow`), so triggering print on mount
    // here is the same single user-requested action, not a second one.
    if (hasTriggeredPrint.current) return;
    if (labels.length === 0) return;
    if (!canonicalAppOrigin) return;
    hasTriggeredPrint.current = true;
    window.print();
  }, [labels.length, canonicalAppOrigin]);

  if (!canonicalAppOrigin) {
    return (
      <ErrorState
        error={
          new AppError(
            "server_error",
            "The application's canonical web address is not configured (APP_BASE_URL). Labels cannot be printed until this is fixed.",
          )
        }
      />
    );
  }

  if (labels.length === 0) {
    return (
      <ErrorState error={new AppError("not_found", "No labels were provided to print.")} />
    );
  }

  return (
    <div className="flex flex-wrap gap-4 p-4 print:gap-0 print:p-0">
      <PrintStyles />
      {labels.map((label, index) => (
        <div key={`${label.token}-${index}`} className={`print-label-item size-${label.size}`}>
          <LabelCard
            token={label.token}
            canonicalAppOrigin={canonicalAppOrigin}
            size={label.size}
            entityTypeLabel={label.entityTypeLabel}
            code={label.code}
            secondaryLine={
              label.lines.length > 0 ? (
                <>
                  {label.lines.map((line, lineIndex) => (
                    <span key={lineIndex} className="block truncate">
                      {line}
                    </span>
                  ))}
                </>
              ) : undefined
            }
          />
        </div>
      ))}
    </div>
  );
}

export function PrintLabelsClient({ canonicalAppOrigin }: { canonicalAppOrigin: string | null }) {
  return (
    <Suspense fallback={null}>
      <PrintLabelsBody canonicalAppOrigin={canonicalAppOrigin} />
    </Suspense>
  );
}
