/** UX-OPS-001B shared primitive: a durable-view tab control for a
 * URL-backed operational queue (Home, Readiness, Incidents). Plain buttons,
 * not an anchor-based tablist, since switching views never navigates to a
 * new route -- only `useViewState`'s `setView` updates the query string.
 * Each tab may carry a small live count badge (e.g. "Attention (3)");
 * `undefined` omits the badge entirely rather than showing "0" for a count
 * that hasn't loaded yet (loading != zero, CLAUDE.md "Empty means loaded
 * successfully with no records"). */
export interface ViewTabItem<V extends string> {
  value: V;
  label: string;
  count?: number;
}

export function ViewTabs<V extends string>({
  items,
  active,
  onChange,
  disabled = false,
}: {
  items: readonly ViewTabItem<V>[];
  active: V;
  onChange: (value: V) => void;
  /** UX-OPS-001D: optional, default `false` (every existing caller is
   * unchanged). `true` while a command attempt on this screen is in flight
   * or unresolved, so switching view can never unmount/replace it. */
  disabled?: boolean;
}) {
  return (
    <div role="tablist" aria-label="Work view" className="flex flex-wrap gap-1 border-b border-wl-border">
      {items.map((item) => {
        const isActive = item.value === active;
        return (
          <button
            key={item.value}
            type="button"
            role="tab"
            aria-selected={isActive}
            disabled={disabled && !isActive}
            onClick={() => onChange(item.value)}
            className={`flex min-h-11 items-center gap-1.5 rounded-t-lg border-b-2 px-3 text-sm font-medium transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-wl-focus ${
              isActive
                ? "border-wl-brand text-wl-text"
                : "border-transparent text-wl-text-secondary hover:text-wl-text disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:text-wl-text-secondary"
            }`}
          >
            {item.label}
            {item.count !== undefined && (
              <span
                className={`inline-flex min-w-5 items-center justify-center rounded-full px-1.5 text-xs font-semibold ${
                  isActive ? "bg-wl-brand-subtle text-wl-brand" : "bg-wl-surface-sunken text-wl-text-secondary"
                }`}
              >
                {item.count}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}
