export interface TabItem {
  id: string;
  label: string;
}

/** Controlled tab strip (UI-OPT-001 Batch A). Deliberately state-less --
 * every existing operational-workspace page (Leafy Production, Harvest,
 * Grading, Packing, Dispatch) owns its own local `activeTab` state rather
 * than URL-based tabs, and this component must keep working for that
 * pattern rather than forcing routing. Visual language mirrors the
 * already-shipped crop-batch detail page tab styling. */
export function Tabs({
  tabs,
  activeId,
  onChange,
  "aria-label": ariaLabel,
}: {
  tabs: TabItem[];
  activeId: string;
  onChange: (id: string) => void;
  "aria-label": string;
}) {
  return (
    <div role="tablist" aria-label={ariaLabel} className="flex gap-2 border-b border-border-subtle">
      {tabs.map((tab) => {
        const active = tab.id === activeId;
        return (
          <button
            key={tab.id}
            type="button"
            role="tab"
            id={`tab-${tab.id}`}
            aria-selected={active}
            aria-controls={`tabpanel-${tab.id}`}
            onClick={() => onChange(tab.id)}
            className={`min-h-11 border-b-2 px-3 py-2 text-sm font-medium ${
              active ? "border-brand-600 text-brand-700" : "border-transparent text-ink-muted hover:text-ink"
            }`}
          >
            {tab.label}
          </button>
        );
      })}
    </div>
  );
}
