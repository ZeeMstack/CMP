import type { ReactNode } from "react";

/** UX-OPS-001A shared primitive: a compact row of context/configuration
 * facts and controls for a Guided command screen -- e.g. active Nursery,
 * Seeding Station, Seed Lot, and derived Crop/Variety facts. Wraps onto a
 * second line on narrow screens rather than stacking each item as its own
 * full-width fieldset. Purely a layout/sizing container: every item's own
 * label association (a real `<label>`, for correct accessible-name/focus
 * behavior) and control are supplied by the caller -- this never wraps
 * children in an implicit label itself, since an item may hold more than
 * one interactive element (e.g. a select plus a "+ Add" link), and wrapping
 * both in one label would fold the link's text into the control's
 * accessible name. */
export function ContextStrip({ children }: { children: ReactNode }) {
  return (
    <div className="flex flex-wrap items-start gap-x-5 gap-y-3 rounded-xl border border-wl-border bg-wl-surface-raised p-3">
      {children}
    </div>
  );
}

export function ContextStripItem({ children, minWidth = "10rem" }: { children: ReactNode; minWidth?: string }) {
  return (
    <div className="flex flex-col gap-1" style={{ minWidth }}>
      {children}
    </div>
  );
}

/** A read-only derived fact (Crop/Variety/Supplier, etc.) inside the strip --
 * labelled "Derived" per the field-placement rules so it is never confused
 * with an operator-entered value. */
export function ContextStripFact({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="flex flex-col gap-1">
      <span className="text-xs font-medium text-wl-text-secondary">{label} · Derived</span>
      <span className="text-sm font-medium text-wl-text">{value}</span>
    </div>
  );
}
