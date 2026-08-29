import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";

/** PILOT-SETUP-001B6: shared brand header for tenant-level standalone
 * routes that sit outside the /farms/[farmId] AppShell tree (Crop/Variety,
 * Production System, Workflow master data -- none of these are farm-scoped,
 * mirroring Carrier Specifications' own already-established rationale: no
 * farmId can be mounted here without either inventing one or guessing at
 * "last visited farm", so this stays a standalone route with the same
 * design tokens/typography as every AppShell-wrapped screen, plus an
 * honest way back into farm context via /farms). */
export function StandaloneShell({ children }: { children: ReactNode }) {
  return (
    <div className="min-h-screen">
      <div className="border-b border-border-subtle bg-surface px-4 py-3 md:px-6">
        <div className="mx-auto flex max-w-5xl items-center justify-between gap-3">
          <div>
            <div className="font-serif text-base font-semibold leading-tight text-brand-900">ImperialFarms CMP</div>
            <div className="mt-0.5 text-[10px] font-semibold uppercase tracking-wide text-ink-muted">
              Crop Management Platform
            </div>
          </div>
          <Link
            href="/farms"
            className="flex min-h-11 items-center gap-1.5 rounded-md px-3 text-sm font-medium text-ink-muted hover:bg-surface-subtle hover:text-ink focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-600"
          >
            <ArrowLeft aria-hidden="true" className="h-4 w-4" />
            Back to Farms
          </Link>
        </div>
      </div>

      <div className="mx-auto max-w-5xl px-4 py-6 md:px-6">{children}</div>
    </div>
  );
}
