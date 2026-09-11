/** Shared class-name recipe for GrowCMP list tables (PILOT-UI-001). Plain
 * exported strings, not a compound component -- list screens keep their own
 * `<table>` markup (sorting, expandable rows, custom cells all vary too much
 * to wrap safely in one pass) but now share one header/row/cell recipe
 * instead of each page hand-rolling a slightly different one. Row height
 * target ~40px (px-4 py-2 at text-sm), per the ticket's 36-48px guidance. */
export const tableWrapperClass = "overflow-x-auto rounded-xl border border-wl-border bg-wl-surface-raised";
export const tableHeadRowClass =
  "border-b border-wl-border bg-wl-surface-sunken text-xs font-medium uppercase tracking-wide text-wl-text-secondary";
export const tableThClass = "px-4 py-2 text-left font-medium";
export const tableTdClass = "px-4 py-2";
export const tableBodyDividerClass = "divide-y divide-wl-border";
export const tableRowHoverClass = "hover:bg-wl-surface-hover";
