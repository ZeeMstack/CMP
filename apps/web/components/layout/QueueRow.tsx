import type { ReactNode } from "react";

/** UX-OPS-001B shared primitive: one compact, selectable row in a unified
 * operational queue (Home, Germination, Seedling, Readiness, Incidents).
 * A single `<button>` per row (>=44px tall for touch) rather than a table
 * row with a separate click target, so the whole row is one accessible
 * control that opens the selected-item inspector -- never a navigation, so
 * the queue itself never unmounts. `sourceLabel` names which underlying
 * source this row came from (Crop/Water/Equipment/Work Item/...) per
 * UX-OPS-001B's "every row must identify its source" requirement for a
 * unified queue; omitted on a single-source queue (Germination/Seedling/
 * Readiness/Incidents) where every row already shares one source. */
export function QueueRow({
  isSelected,
  onSelect,
  title,
  sourceLabel,
  context,
  status,
  meta,
  action,
}: {
  isSelected: boolean;
  onSelect: () => void;
  title: ReactNode;
  sourceLabel?: string;
  context?: ReactNode;
  status?: ReactNode;
  meta?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <li>
      <div
        className={`flex min-h-11 items-center gap-3 border-l-2 px-3.5 py-2 transition-colors ${
          isSelected ? "border-l-wl-brand bg-wl-brand-subtle" : "border-l-transparent hover:bg-wl-surface-hover"
        }`}
      >
        <button
          type="button"
          onClick={onSelect}
          aria-current={isSelected ? "true" : undefined}
          className="flex min-w-0 flex-1 flex-col items-start gap-0.5 text-left focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-wl-focus"
        >
          <span className="flex w-full items-center gap-2 text-sm font-medium text-wl-text">
            {sourceLabel && (
              <span className="shrink-0 rounded bg-wl-surface-sunken px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-wl-text-secondary">
                {sourceLabel}
              </span>
            )}
            <span className="min-w-0 truncate">{title}</span>
          </span>
          {context && <span className="max-w-full truncate text-xs text-wl-text-secondary">{context}</span>}
        </button>
        {status && <div className="shrink-0">{status}</div>}
        {meta && <div className="shrink-0 text-xs text-wl-text-secondary">{meta}</div>}
        {action && <div className="shrink-0">{action}</div>}
      </div>
    </li>
  );
}

export function QueueList({ children, label }: { children: ReactNode; label: string }) {
  return (
    <ul role="list" aria-label={label} className="divide-y divide-wl-border">
      {children}
    </ul>
  );
}

/** UX-OPS-001B R2: a compact, queue-row-height failure state for ONE
 * segment/source inside a unified queue -- named source, concise reason,
 * and an inline Retry, at roughly the same height as an ordinary
 * `QueueRow` (never the global `ErrorState` card's large padding and
 * multi-line explanatory copy, which would let a single failed source
 * dominate a bounded region shared with working sibling segments).
 * `role="alert"` so assistive tech still announces it despite the compact
 * size. Purely presentational -- never disables or hides sibling
 * segments; the caller renders this in place of just the one failed
 * segment's own rows. */
export function QueueSourceFailureRow({
  sourceLabel,
  message,
  onRetry,
}: {
  sourceLabel: string;
  message: string;
  onRetry: () => void;
}) {
  return (
    <div
      role="alert"
      className="flex min-h-11 items-center gap-3 border-l-2 border-l-wl-flag-fg bg-wl-flag-bg px-3.5 py-2"
    >
      <span className="min-w-0 flex-1 truncate text-sm text-wl-flag-fg">
        <span className="font-medium">{sourceLabel}</span> unavailable — {message}
      </span>
      <button
        type="button"
        onClick={onRetry}
        className="shrink-0 rounded-md border border-wl-border-strong bg-wl-surface-raised px-2.5 py-1 text-xs font-medium text-wl-text hover:bg-wl-surface-hover focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-wl-focus"
      >
        Retry
      </button>
    </div>
  );
}
