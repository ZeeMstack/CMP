"use client";

import { useState } from "react";

/** PILOT-UX-002A: shared compact loss-entry pattern for the Production
 * Transfer and InterSalads source rows. The four detailed loss categories
 * (damage/QC rejected/sample/other + note) remain exactly as-is -- this
 * only collapses them behind a one-line "Loss: N" summary in the normal
 * (zero-loss) case, per the ticket's explicit instruction not to let four
 * zero-value inputs dominate every source row. Starts open when the row
 * already carries a nonzero loss (e.g. re-opening a draft) so an existing
 * value is never hidden by default; the operator's own open/closed choice
 * after that is respected rather than being forced open again on every
 * keystroke. */
export function CompactLossDisclosure({ total, children }: { total: number; children: React.ReactNode }) {
  const [open, setOpen] = useState(total > 0);
  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center gap-1.5 text-sm">
        <span className="text-wl-text-secondary">Loss:</span>
        <span className="mr-1.5 font-medium text-wl-text">{total.toLocaleString()}</span>
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          className="min-h-11 text-xs font-medium text-wl-brand hover:underline sm:min-h-0"
        >
          {open ? "Hide loss details" : "Add / edit loss details"}
        </button>
      </div>
      {open && <div className="flex flex-col gap-3">{children}</div>}
    </div>
  );
}
