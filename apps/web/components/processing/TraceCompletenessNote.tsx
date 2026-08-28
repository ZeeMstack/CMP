import type { TraceCompleteness } from "@/lib/api/client";

/** UI-OPT-001: surfaces the backend's own `Completeness` verdict on a
 * trace/impact result honestly, rather than presenting every trace as
 * unconditionally exhaustive. `trace_complete: false` and any
 * `limitations`/`capability_limitations` come straight from the read
 * model -- never invented or summarized away here. */
export function TraceCompletenessNote({ completeness }: { completeness: TraceCompleteness }) {
  if (completeness.trace_complete && completeness.limitations.length === 0 && completeness.capability_limitations.length === 0) {
    return null;
  }
  return (
    <div className="rounded-md border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900">
      <p className="font-medium">
        {completeness.trace_complete ? "Trace complete, with noted limitations" : "This trace is not complete"}
      </p>
      {completeness.limitations.map((l) => (
        <p key={l.code} className="mt-1 text-xs">
          {l.message}
        </p>
      ))}
      {completeness.capability_limitations.map((c) => (
        <p key={c} className="mt-1 text-xs">
          {c}
        </p>
      ))}
    </div>
  );
}
