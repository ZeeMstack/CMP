"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";

/** UX-OPS-001A/R1 shared primitive: a single-DOM primary-action surface for
 * a Guided command screen. There is exactly one rendered action control --
 * never a desktop copy and a separate mobile copy. At the desktop
 * breakpoint (`lg`) this renders in normal flow, as the bottom of the
 * caller's sticky summary rail (`SplitWorkspace`'s `rail` already applies
 * `lg:sticky lg:top-4` to its own box). Below `lg`, this same element
 * switches to `fixed`, pinning it to the bottom of the viewport so the
 * primary action stays reachable while the operator scrolls a long
 * Configure/Review workspace -- the rail's other summary facts stay in
 * normal in-flow order above it; only this action surface persists.
 *
 * Callers MUST add `STICKY_ACTION_BAR_SPACER_CLASS` to their scrolling page
 * container so the fixed bar (below `lg`) never overlaps the last field,
 * a validation message, or a tray row -- the class reserves matching
 * bottom space there and is a no-op at `lg` and above, where this bar is
 * back in normal flow and needs no reserved space. */
export function StickyActionBar({ blockers, children }: { blockers?: ReactNode; children: ReactNode }) {
  // UX-OPS-001C/R1: the bar's height is not fixed -- blockers/uncertain-
  // outcome copy can make it taller than `STICKY_ACTION_BAR_SPACER_CLASS`
  // reserves (proven at 390x844: an uncertain Inspect Crop bar covered the
  // last ~33px of content). An in-flow placeholder of the bar's own
  // measured height (below `lg` only, where the bar is fixed) keeps the
  // page's scrollable end exactly clear of it, whatever it contains.
  const barRef = useRef<HTMLDivElement>(null);
  const [barHeight, setBarHeight] = useState(0);
  useEffect(() => {
    const el = barRef.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(() => setBarHeight(el.getBoundingClientRect().height));
    observer.observe(el);
    return () => observer.disconnect();
  }, []);
  return (
    <>
      <div aria-hidden="true" className="lg:hidden" style={{ height: barHeight }} />
      <div
        ref={barRef}
        className="fixed inset-x-0 bottom-0 z-20 flex flex-col gap-2 border-t border-wl-border bg-wl-surface-raised px-4 pb-[max(0.75rem,env(safe-area-inset-bottom))] pt-3 shadow-[0_-2px_8px_rgba(0,0,0,0.06)] lg:static lg:z-auto lg:border-t-0 lg:bg-transparent lg:p-0 lg:shadow-none"
      >
        {blockers}
        {children}
      </div>
    </>
  );
}

/** Reserves room at the bottom of a scrolling Configure/Review page for the
 * fixed mobile/tablet action bar above -- a no-op at `lg` and above. */
export const STICKY_ACTION_BAR_SPACER_CLASS = "pb-24 lg:pb-0";
