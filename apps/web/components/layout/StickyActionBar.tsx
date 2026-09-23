"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";

/** Fallback reserved height (px) below `lg` before the bar is measured, or
 * permanently where `ResizeObserver` is unavailable -- the bar's usual
 * single-action height (padding + one 36-44px control + safe-area slack). */
export const STICKY_ACTION_BAR_FALLBACK_HEIGHT_PX = 96;

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
 * Bottom clearance below `lg` is owned entirely by this component (see
 * the measured placeholder below) -- callers add no spacer of their own. */
export function StickyActionBar({ blockers, children }: { blockers?: ReactNode; children: ReactNode }) {
  // UX-OPS-001C/R2: the ONE mobile-clearance mechanism. The bar's height is
  // not fixed (blockers/uncertain-outcome copy make it taller), so below
  // `lg` -- where the bar is `fixed` -- an in-flow placeholder of the bar's
  // own measured height keeps the page's scrollable end exactly clear of
  // it. Callers add no bottom padding of their own (the previous
  // `pb-24` spacer class double-reserved space and was removed). At `lg`+
  // the placeholder is hidden and the bar is back in normal flow.
  const barRef = useRef<HTMLDivElement>(null);
  const [barHeight, setBarHeight] = useState(STICKY_ACTION_BAR_FALLBACK_HEIGHT_PX);
  useEffect(() => {
    const el = barRef.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(() => {
      const measured = el.getBoundingClientRect().height;
      if (measured > 0) setBarHeight(measured);
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);
  return (
    <>
      <div aria-hidden="true" data-testid="sticky-action-bar-spacer" className="lg:hidden" style={{ height: barHeight }} />
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
