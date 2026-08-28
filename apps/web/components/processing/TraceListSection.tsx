/** UI-OPT-001: one titled, counted list of trace rows -- shared by every
 * Traceability result panel (Crop Batch/Harvested Produce Lot impact,
 * Finished Goods Lot trace) since all of them repeat the same "bordered
 * card list of related records" shape 6+ times. Purely presentational; the
 * caller owns what each row renders. Renders nothing when there are no
 * items and no caller-supplied `emptyLabel` -- an empty backward/forward
 * trace section is not worth a heading if the caller has nothing to say
 * about the absence. */
export function TraceListSection<T>({
  title,
  items,
  renderItem,
  keyFor,
  emptyLabel,
}: {
  title: string;
  items: T[];
  renderItem: (item: T) => React.ReactNode;
  keyFor: (item: T) => string;
  emptyLabel?: string;
}) {
  if (items.length === 0 && !emptyLabel) return null;
  return (
    <div>
      {/* One flat text node, not `{title}` plus a nested `<span>` for the
          count -- RTL's `getByText` only matches an element's own direct
          text, so splitting this across a child element would silently
          break every exact-string query against this heading. */}
      <h3 className="mb-2 font-serif text-sm font-semibold text-ink">
        {title} ({items.length})
      </h3>
      {items.length === 0 ? (
        <p className="text-sm text-ink-muted">{emptyLabel}</p>
      ) : (
        <ul className="flex flex-col gap-2">
          {items.map((item) => (
            <li key={keyFor(item)} className="rounded-md border border-border-subtle bg-surface p-2 text-sm">
              {renderItem(item)}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
