/** Shared class-name recipe for GrowCMP list tables (PILOT-UI-001, density
 * per PILOT-UI-002's approved spec: header padding 6px/14px, row padding
 * 7px/14px, 11px uppercase column labels). Plain exported strings, not a
 * compound component -- list screens keep their own `<table>` markup
 * (sorting, expandable rows, custom cells all vary too much to wrap safely
 * in one pass) but now share one header/row/cell recipe instead of each
 * page hand-rolling a slightly different one. */
export const tableWrapperClass = "overflow-x-auto rounded-xl border border-wl-border bg-wl-surface-raised";
export const tableHeadRowClass =
  "border-b border-wl-border bg-wl-surface-sunken text-[11px] font-medium uppercase tracking-[0.05em] text-wl-text-secondary";
export const tableThClass = "px-3.5 py-1.5 text-left font-medium";
export const tableTdClass = "px-3.5 py-[7px]";
export const tableBodyDividerClass = "divide-y divide-wl-border";
export const tableRowHoverClass = "hover:bg-wl-surface-hover";
