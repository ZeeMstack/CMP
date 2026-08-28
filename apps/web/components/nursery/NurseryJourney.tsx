"use client";

import { ArrowRight } from "lucide-react";
import Link from "next/link";

export type NurseryStage = "seeding" | "germination" | "seedling" | "intersalads";

const STAGES: { id: NurseryStage; label: string; hrefSuffix: string }[] = [
  { id: "seeding", label: "Seeding", hrefSuffix: "/nursery/sowings/new" },
  { id: "germination", label: "Germination", hrefSuffix: "/nursery/germination" },
  { id: "seedling", label: "Seedling", hrefSuffix: "/nursery/seedling" },
  // Operator-facing label only -- the route stays /nursery/intersalads and
  // every internal identifier stays InterSalads (CEO_ALIGNMENT_SPEC.md
  // terminology decisions).
  { id: "intersalads", label: "Transfer to Inter Leafy Greens", hrefSuffix: "/nursery/intersalads" },
];

/** Purely presentational route indicator shared by the four Nursery
 * screens. Each stage is a real Link to its existing route -- clicking one
 * is plain navigation, nothing else. It has no data dependency and makes
 * no claim about the underlying Batch/Tray's own biological stage; moving
 * between pages here never implies the biological entity itself
 * transitioned (that only happens via the existing backend commands each
 * page's own form submits). */
export function NurseryJourney({ farmId, current }: { farmId: string; current: NurseryStage }) {
  return (
    <nav aria-label="Nursery journey" className="mb-6 overflow-x-auto">
      <ol className="flex min-w-max items-center gap-1">
        {STAGES.map((stage, index) => {
          const isCurrent = stage.id === current;
          return (
            <li key={stage.id} className="flex items-center gap-1">
              <Link
                href={`/farms/${farmId}${stage.hrefSuffix}`}
                aria-current={isCurrent ? "step" : undefined}
                className={`flex min-h-11 items-center gap-1.5 rounded-full border px-3 text-xs font-semibold transition-colors sm:text-sm ${
                  isCurrent
                    ? "border-brand-700 bg-brand-700 text-white"
                    : "border-border-subtle bg-surface text-ink-muted hover:border-brand-300 hover:text-ink"
                }`}
              >
                {/* Current stage is never conveyed by color alone. */}
                {isCurrent && <span className="sr-only">Current: </span>}
                {stage.label}
              </Link>
              {index < STAGES.length - 1 && (
                <ArrowRight aria-hidden="true" className="h-3.5 w-3.5 shrink-0 text-ink-muted" />
              )}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
