import Link from "next/link";

import { ReconciliationSummary } from "@/components/processing/ReconciliationSummary";
import { TraceCompletenessNote } from "@/components/processing/TraceCompletenessNote";
import { TraceListSection } from "@/components/processing/TraceListSection";
import type { FinishedGoodsLotTraceRead } from "@/lib/api/client";

function fmtTime(iso: string) {
  return new Date(iso).toLocaleString();
}

/** UI-OPT-001: renders `FinishedGoodsLotTraceRead` -- the full backward
 * trace from one Finished Goods Lot back through its Packing event, source
 * Graded Produce Lots/Grading events, source Harvested Produce Lots/Harvest
 * events, Seed origin, plus its own storage movements/dispatches/quality
 * holds. Read-only. The Packing reconciliation reuses the same
 * `ReconciliationSummary` component (and the same 3-way, no-sample/
 * no-remainder field set) as the live Packing screens -- never a
 * re-derived or re-labelled copy of that math. */
export function TraceFinishedGoodsLotPanel({
  farmId,
  data,
  locationLabelById,
}: {
  farmId: string;
  data: FinishedGoodsLotTraceRead;
  locationLabelById?: Map<string, string>;
}) {
  return (
    <div className="flex flex-col gap-4">
      <TraceCompletenessNote completeness={data.completeness} />

      <dl className="grid grid-cols-2 gap-x-4 gap-y-3 rounded-xl border border-border-subtle bg-surface p-4 text-sm sm:grid-cols-3">
        <div>
          <dt className="text-xs font-medium uppercase tracking-wide text-ink-muted">Finished Goods Lot</dt>
          <dd className="text-ink">
            <Link href={`/farms/${farmId}/processing/finished-goods/${data.subject.finished_goods_lot_id}`} className="font-medium hover:underline">
              {data.subject.code}
            </Link>
          </dd>
        </div>
        <div>
          <dt className="text-xs font-medium uppercase tracking-wide text-ink-muted">Net packed</dt>
          <dd className="text-ink">{data.subject.net_packed_weight_kg} kg / {data.subject.package_count} pkg</dd>
        </div>
        <div>
          <dt className="text-xs font-medium uppercase tracking-wide text-ink-muted">Available now</dt>
          <dd className="text-ink">{data.subject.available_weight_kg} kg / {data.subject.available_package_count} pkg</dd>
        </div>
      </dl>

      <div>
        <h3 className="mb-2 font-serif text-sm font-semibold text-ink">Packing event</h3>
        <ReconciliationSummary
          inputLabel="Total consumed input"
          inputValue={Number(data.packing_event.total_input_weight_kg)}
          unit="kg"
          parts={[
            { label: "Packed output", value: Number(data.packing_event.packed_output_weight_kg) },
            { label: "Process loss", value: Number(data.packing_event.process_loss_weight_kg) },
            { label: "Rejected", value: Number(data.packing_event.rejected_weight_kg) },
          ]}
        />
      </div>

      <TraceListSection
        title="Source Graded Produce Lots"
        items={data.graded_produce_lots}
        keyFor={(l) => l.graded_produce_lot_id}
        renderItem={(l) => (
          <div className="flex flex-wrap items-center justify-between gap-2">
            <Link href={`/farms/${farmId}/processing/graded-lots/${l.graded_produce_lot_id}`} className="font-medium text-ink hover:underline">
              {l.code}
            </Link>
            <span className="text-ink-muted">{l.original_received_weight_kg} kg — {fmtTime(l.effective_time)}</span>
          </div>
        )}
      />

      <TraceListSection
        title="Source Harvested Produce Lots"
        items={data.produce_lots}
        keyFor={(l) => l.harvested_produce_lot_id}
        renderItem={(l) => (
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="font-medium text-ink">{l.code}</span>
            <span className="text-ink-muted">{l.total_harvested_weight_kg} kg — {fmtTime(l.effective_time)}</span>
          </div>
        )}
      />

      <TraceListSection
        title="Seed origin"
        items={data.seed_origins}
        keyFor={(s) => s.sowing_event_line_id}
        emptyLabel="No Seed Lot origin recorded for this trace."
        renderItem={(s) => <span className="text-ink-muted">Seed Lot {s.seed_lot_code}</span>}
      />

      <TraceListSection
        title="Storage movements"
        items={data.storage_movements}
        keyFor={(m) => m.movement_id}
        emptyLabel="No Cold Storage movements recorded for this Lot."
        renderItem={(m) => {
          const destLabel = m.destination_location_id ? locationLabelById?.get(m.destination_location_id) : null;
          const sourceLabel = m.source_location_id ? locationLabelById?.get(m.source_location_id) : null;
          return (
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="font-medium capitalize text-ink">
                {m.movement_kind}
                {(sourceLabel || destLabel) && (
                  <span className="ml-1 font-normal text-ink-muted">
                    {sourceLabel && `from ${sourceLabel}`}
                    {sourceLabel && destLabel && " "}
                    {destLabel && `to ${destLabel}`}
                  </span>
                )}
              </span>
              <span className="text-ink-muted">{m.moved_weight_kg} kg / {m.moved_package_count} pkg — {fmtTime(m.effective_time)}</span>
            </div>
          );
        }}
      />

      <TraceListSection
        title="Dispatches"
        items={data.dispatches}
        keyFor={(l) => l.dispatch_line_id}
        emptyLabel="This Lot has not been dispatched yet."
        renderItem={(l) => (
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="font-medium text-ink">{l.dispatch_event_code}</span>
            <span className="text-ink-muted">{l.dispatched_weight_kg} kg / {l.dispatched_package_count} pkg — {fmtTime(l.effective_time)}</span>
          </div>
        )}
      />

      <TraceListSection
        title="Quality holds"
        items={data.quality}
        keyFor={(q) => q.quality_hold_id}
        emptyLabel="No Quality Holds recorded anywhere in this trace."
        renderItem={(q) => (
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="font-medium text-ink">{q.reason_text || q.reason_code}</span>
            <span className={q.is_open ? "font-medium text-red-700" : "text-ink-muted"}>
              {q.is_open ? "Open" : "Released"} — {fmtTime(q.effective_time)}
            </span>
          </div>
        )}
      />
    </div>
  );
}
