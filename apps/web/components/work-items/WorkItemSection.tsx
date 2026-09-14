import { tableBodyDividerClass, tableHeadRowClass, tableThClass, tableWrapperClass } from "@/components/ui/table";
import type { FarmWorkItemRead } from "@/lib/api/client";

import { WorkItemRow } from "./WorkItemRow";

/** One board section (My Work / Blocked / In Progress / Carryover / Farm
 * Work) -- a plain compact table, never a card grid (CLAUDE.md "no giant
 * dashboard cards"). Renders nothing when the section is empty and
 * `hideWhenEmpty` is set (used for optional sections like Blocked), or a
 * one-line empty note otherwise. */
export function WorkItemSection({
  title,
  items,
  farmId,
  currentUserId,
  hideWhenEmpty = false,
  emptyLabel = "Nothing here",
}: {
  title: string;
  items: FarmWorkItemRead[];
  farmId: string;
  currentUserId?: string;
  hideWhenEmpty?: boolean;
  emptyLabel?: string;
}) {
  if (items.length === 0 && hideWhenEmpty) return null;

  return (
    <section className="mt-6">
      <h2 className="mb-2 flex items-center gap-2 font-serif text-base font-semibold text-wl-text">
        {title}
        <span className="inline-flex min-w-6 items-center justify-center rounded-full bg-wl-brand-subtle px-1.5 text-xs font-semibold text-wl-brand">
          {items.length}
        </span>
      </h2>
      {items.length === 0 ? (
        <p className="text-sm text-wl-text-secondary">{emptyLabel}</p>
      ) : (
        <div className={tableWrapperClass}>
          <table className="w-full text-left text-sm">
            <thead>
              <tr className={tableHeadRowClass}>
                <th className={tableThClass}>Work</th>
                <th className={tableThClass}>Context</th>
                <th className={tableThClass}>Owner</th>
                <th className={tableThClass}>Due</th>
                <th className={tableThClass}>Status</th>
                <th className={tableThClass}>Next action</th>
              </tr>
            </thead>
            <tbody className={tableBodyDividerClass}>
              {items.map((item) => (
                <WorkItemRow key={item.id} item={item} farmId={farmId} currentUserId={currentUserId} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
