"use client";

import { ArrowRight } from "lucide-react";
import Link from "next/link";

export type NurseryStage = "seeding" | "germination" | "seedling" | "intersalads" | "intervines";

const STAGES: { id: NurseryStage; label: string; hrefSuffix: string }[] = [
  { id: "seeding", label: "Seeding", hrefSuffix: "/nursery/sowings/new" },
  { id: "germination", label: "Germination", hrefSuffix: "/nursery/germination" },
  { id: "seedling", label: "Seedling", hrefSuffix: "/nursery/seedling" },
  // Operator-facing label only -- the route stays /nursery/intersalads and
  // every internal identifier stays InterSalads (CEO_ALIGNMENT_SPEC.md
  // terminology decisions).
  { id: "intersalads", label: "Transfer to Inter Leafy Greens", hrefSuffix: "/nursery/intersalads" },
  // VINES-OPS-001A: the sibling Vines destination from the same Seedling
  // stage -- which of the two a given Batch actually uses depends on its
  // own crop workflow, never a branch here (this nav is purely a route
  // indicator, crop-agnostic like every other Nursery screen).
  { id: "intervines", label: "Transfer to InterVines", hrefSuffix: "/nursery/intervines" },
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
                    ? "border-wl-brand bg-wl-brand text-wl-text-on-brand"
                    : "border-wl-border bg-wl-surface-raised text-wl-text-secondary hover:border-wl-brand hover:text-wl-text"
                }`}
              >
                {/* Current stage is never conveyed by color alone. */}
                {isCurrent && <span className="sr-only">Current: </span>}
                {stage.label}
              </Link>
              {index < STAGES.length - 1 && (
                <ArrowRight aria-hidden="true" className="h-3.5 w-3.5 shrink-0 text-wl-text-secondary" />
              )}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
