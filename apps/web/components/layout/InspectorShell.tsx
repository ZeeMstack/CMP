import type { ReactNode } from "react";

/** UX-OPS-001B shared primitive: the selected-item inspector/action rail
 * for a queue+inspector workspace (Home, Germination, Seedling, Readiness,
 * Incidents). Sits in `SplitWorkspace`'s `rail` slot. Purely a header/body
 * shell -- the caller supplies its own facts and action controls as
 * children, since every source's valid fields/actions differ. */
export function InspectorShell({
  title,
  subtitle,
  status,
  onClose,
  children,
}: {
  title: ReactNode;
  subtitle?: ReactNode;
  status?: ReactNode;
  onClose?: () => void;
  children: ReactNode;
}) {
  return (
    <div className="flex flex-col gap-3 rounded-xl border border-wl-border bg-wl-surface-raised p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 flex-col gap-0.5">
          <h2 className="truncate font-serif text-base font-semibold text-wl-text">{title}</h2>
          {subtitle && <p className="truncate text-xs text-wl-text-secondary">{subtitle}</p>}
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {status}
          {onClose && (
            <button
              type="button"
              onClick={onClose}
              aria-label="Close inspector"
              className="flex h-9 w-9 items-center justify-center rounded-lg text-wl-text-secondary hover:bg-wl-surface-hover focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-wl-focus"
            >
              ×
            </button>
          )}
        </div>
      </div>
      {children}
    </div>
  );
}

/** Shown in the rail when nothing is selected yet -- never an error, never
 * a blank box (an unselected inspector is a normal, expected state). */
export function InspectorEmptyState({ label = "Select a row to see details and actions." }: { label?: string }) {
  return (
    <div
      role="status"
      className="flex min-h-[8rem] items-center justify-center rounded-xl border border-dashed border-wl-border p-4 text-center text-sm text-wl-text-secondary"
    >
      {label}
    </div>
  );
}
