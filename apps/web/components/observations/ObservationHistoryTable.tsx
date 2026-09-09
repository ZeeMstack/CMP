"use client";

import { Fragment, useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";

import type { ObservationEventRead } from "@/lib/api/client";
import { formatDateTime } from "@/lib/format/datetime";
import { formatObservationValue, formatObservationValueTarget } from "@/lib/format/observationValue";

/** AGRONOMY-OPS-001: compact per-batch Observation log. Every row is one
 * ObservationEvent, expandable to its individual values (an event usually
 * carries several -- one Record command may bundle many definitions, see
 * `RecordObservationForm`). No "Recorded by" column: this codebase has no
 * existing display-name resolution for `actor_user_id` anywhere yet (every
 * other operational history panel already omits it too, e.g. Plant Loss/
 * Harvest History) -- surfacing a raw UUID would violate the "no UUIDs in
 * normal UI" rule, so this is a known, tracked limitation rather than a
 * silently dropped requirement (see docs/product/OPEN-QUESTIONS.md). */
export function ObservationHistoryTable({
  events,
  timeZone,
}: {
  events: ObservationEventRead[];
  timeZone?: string;
}) {
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  function toggle(id: string) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  return (
    <div className="overflow-x-auto rounded-xl border border-border-subtle bg-surface">
      <table className="w-full min-w-[640px] text-sm">
        <thead>
          <tr className="border-b border-border-subtle text-left text-xs font-medium uppercase tracking-wide text-ink-muted">
            <th className="w-8 px-3 py-2" />
            <th className="px-3 py-2">Date</th>
            <th className="px-3 py-2">Stage</th>
            <th className="px-3 py-2">Values</th>
            <th className="px-3 py-2">Note</th>
          </tr>
        </thead>
        <tbody>
          {[...events]
            .sort((a, b) => b.effective_time.localeCompare(a.effective_time))
            .map((event) => {
              const isOpen = expanded.has(event.id);
              const summary = event.values
                .slice(0, 2)
                .map((v) => `${v.definition.name}: ${formatObservationValue(v)}`)
                .join(" · ");
              const more = event.values.length > 2 ? ` +${event.values.length - 2} more` : "";
              return (
                <Fragment key={event.id}>
                  <tr
                    className="cursor-pointer border-b border-border-subtle last:border-0 hover:bg-surface-subtle"
                    onClick={() => toggle(event.id)}
                  >
                    <td className="px-3 py-2 text-ink-muted">
                      {isOpen ? (
                        <ChevronDown aria-hidden="true" className="h-4 w-4" />
                      ) : (
                        <ChevronRight aria-hidden="true" className="h-4 w-4" />
                      )}
                    </td>
                    <td className="whitespace-nowrap px-3 py-2 text-ink">
                      {formatDateTime(event.effective_time, timeZone)}
                    </td>
                    <td className="whitespace-nowrap px-3 py-2 text-ink">{event.stage.name}</td>
                    <td className="px-3 py-2 text-ink">
                      {event.values.length === 0 ? "—" : `${summary}${more}`}
                    </td>
                    <td className="max-w-[24ch] truncate px-3 py-2 text-ink-muted">{event.note ?? ""}</td>
                  </tr>
                  {isOpen && (
                    <tr className="border-b border-border-subtle bg-surface-subtle last:border-0">
                      <td />
                      <td colSpan={4} className="px-3 py-2">
                        <dl className="grid grid-cols-1 gap-x-6 gap-y-1.5 sm:grid-cols-2">
                          {event.values.map((v) => (
                            <div key={v.id} className="flex items-baseline justify-between gap-3 text-sm">
                              <dt className="text-ink-muted">
                                {v.definition.name}
                                <span className="text-xs"> ({formatObservationValueTarget(v)})</span>
                              </dt>
                              <dd className="font-medium text-ink">{formatObservationValue(v)}</dd>
                            </div>
                          ))}
                        </dl>
                      </td>
                    </tr>
                  )}
                </Fragment>
              );
            })}
        </tbody>
      </table>
    </div>
  );
}
