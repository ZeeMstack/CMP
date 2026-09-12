"use client";

import { ArrowRight } from "lucide-react";
import Link from "next/link";

export type NurseryStage = "seeding" | "germination" | "seedling" | "intersalads" | "intervines";

const SEQUENTIAL_STAGES: { id: NurseryStage; label: string; hrefSuffix: string }[] = [
  { id: "seeding", label: "Seeding", hrefSuffix: "/nursery/sowings/new" },
  { id: "germination", label: "Germination", hrefSuffix: "/nursery/germination" },
  { id: "seedling", label: "Seedling", hrefSuffix: "/nursery/seedling" },
];

// PILOT-UX-003: these two are ALTERNATIVE destinations from the same
// Seedling stage -- which one a given Batch actually uses depends on its
// own crop workflow, never both in sequence. Grouped together and joined
// by "or" (never a further arrow between them) so the layout itself says
// this, not just the code comment.
const BRANCH_STAGES: { id: NurseryStage; label: string; hrefSuffix: string }[] = [
  // Operator-facing label only -- the route stays /nursery/intersalads and
  // every internal identifier stays InterSalads (CEO_ALIGNMENT_SPEC.md
  // terminology decisions).
  { id: "intersalads", label: "Transfer to Inter Leafy Greens", hrefSuffix: "/nursery/intersalads" },
  // VINES-OPS-001A: the sibling Vines destination.
  { id: "intervines", label: "Transfer to InterVines", hrefSuffix: "/nursery/intervines" },
];

function StagePill({ farmId, stage, isCurrent }: { farmId: string; stage: (typeof SEQUENTIAL_STAGES)[number]; isCurrent: boolean }) {
  return (
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
  );
}

/** Purely presentational route indicator shared by the five Nursery
 * screens. Each stage is a real Link to its existing route -- clicking one
 * is plain navigation, nothing else. It has no data dependency and makes
 * no claim about the underlying Batch/Tray's own biological stage; moving
 * between pages here never implies the biological entity itself
 * transitioned (that only happens via the existing backend commands each
 * page's own form submits).
 *
 * PILOT-UX-003: InterSalads and InterVines are laid out as a joined,
 * "or"-separated pair after one arrow from Seedling -- not as two more
 * sequential arrow-linked steps -- since a Batch takes exactly one of
 * these two, never both in order. */
export function NurseryJourney({ farmId, current }: { farmId: string; current: NurseryStage }) {
  return (
    <nav aria-label="Nursery journey" className="mb-6 overflow-x-auto">
      <ol className="flex min-w-max items-center gap-1">
        {SEQUENTIAL_STAGES.map((stage) => (
          <li key={stage.id} className="flex items-center gap-1">
            <StagePill farmId={farmId} stage={stage} isCurrent={stage.id === current} />
            <ArrowRight aria-hidden="true" className="h-3.5 w-3.5 shrink-0 text-wl-text-secondary" />
          </li>
        ))}
        <li className="flex items-center gap-1.5 rounded-full border border-dashed border-wl-border px-2 py-1">
          {BRANCH_STAGES.map((stage, index) => (
            <span key={stage.id} className="flex items-center gap-1.5">
              {index > 0 && <span className="text-xs font-medium text-wl-text-secondary">or</span>}
              <StagePill farmId={farmId} stage={stage} isCurrent={stage.id === current} />
            </span>
          ))}
        </li>
      </ol>
    </nav>
  );
}
