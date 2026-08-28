import Link from "next/link";

import { TraceCompletenessNote } from "@/components/processing/TraceCompletenessNote";
import { TraceListSection } from "@/components/processing/TraceListSection";
import type {
  FinishedGoodsLotImpactRead, ImpactSummary, TraceCompleteness, TraceDispatchLineRead,
  TraceGradedProduceLotRead, TraceHarvestedProduceLotRead, TraceLocationBalanceRead, TracePackingInputLineRead,
} from "@/lib/api/client";

function fmtTime(iso: string) {
  return new Date(iso).toLocaleString();
}

/** UI-OPT-001: renders the shared shape of a forward "impact" trace --
 * `CropBatchImpactRead` and `HarvestedProduceLotImpactRead` carry the same
 * downstream fields (produce lots -> packing inputs -> graded lots ->
 * finished goods -> storage -> dispatches, plus a summary/completeness
 * verdict), differing only in what extra context the entry point itself
 * contributes (Crop Batch adds Lineage/Harvest Events, rendered by the
 * caller as extra children rather than duplicated here). Read-only: no
 * mutation controls, nothing here can change domain state. */
export function TraceImpactPanel({
  farmId,
  summary,
  completeness,
  produceLots,
  packingInputs,
  gradedProduceLots,
  finishedGoods,
  storage,
  dispatches,
  locationLabelById,
  children,
}: {
  farmId: string;
  summary: ImpactSummary;
  completeness: TraceCompleteness;
  produceLots: TraceHarvestedProduceLotRead[];
  packingInputs: TracePackingInputLineRead[];
  gradedProduceLots: TraceGradedProduceLotRead[];
  finishedGoods: FinishedGoodsLotImpactRead[];
  storage: TraceLocationBalanceRead[];
  dispatches: TraceDispatchLineRead[];
  locationLabelById?: Map<string, string>;
  /** Entry-type-specific extra sections (e.g. Crop Batch's Lineage/Harvest
   * Events) rendered between the summary and the shared downstream lists. */
  children?: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-4">
      <TraceCompletenessNote completeness={completeness} />

      <dl className="grid grid-cols-2 gap-x-4 gap-y-3 rounded-xl border border-border-subtle bg-surface p-4 text-sm sm:grid-cols-4">
        <div>
          <dt className="text-xs font-medium uppercase tracking-wide text-ink-muted">Harvested Lots affected</dt>
          <dd className="font-semibold text-ink">{summary.affected_harvested_produce_lot_count}</dd>
        </div>
        <div>
          <dt className="text-xs font-medium uppercase tracking-wide text-ink-muted">Graded Lots affected</dt>
          <dd className="font-semibold text-ink">{summary.affected_graded_produce_lot_count}</dd>
        </div>
        <div>
          <dt className="text-xs font-medium uppercase tracking-wide text-ink-muted">Finished Goods Lots affected</dt>
          <dd className="font-semibold text-ink">{summary.affected_finished_goods_lot_count}</dd>
        </div>
        <div>
          <dt className="text-xs font-medium uppercase tracking-wide text-ink-muted">Dispatches affected</dt>
          <dd className="font-semibold text-ink">{summary.affected_dispatch_event_count}</dd>
        </div>
        <div className="sm:col-span-2">
          <dt className="text-xs font-medium uppercase tracking-wide text-ink-muted">Potentially affected — available</dt>
          <dd className="text-ink">
            {summary.potentially_affected_available_weight_kg} kg / {summary.potentially_affected_available_package_count} pkg
          </dd>
        </div>
        <div className="sm:col-span-2">
          <dt className="text-xs font-medium uppercase tracking-wide text-ink-muted">Potentially affected — placed / unplaced</dt>
          <dd className="text-ink">
            {summary.potentially_affected_placed_weight_kg} kg placed — {summary.potentially_affected_unplaced_weight_kg} kg unplaced
          </dd>
        </div>
      </dl>

      {children}

      <TraceListSection
        title="Harvested Produce Lots"
        items={produceLots}
        keyFor={(l) => l.harvested_produce_lot_id}
        renderItem={(l) => (
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="font-medium text-ink">{l.code}</span>
            <span className="text-ink-muted">
              {l.total_harvested_weight_kg} kg — {fmtTime(l.effective_time)}
            </span>
          </div>
        )}
      />

      <TraceListSection
        title="Graded Produce Lots"
        items={gradedProduceLots}
        keyFor={(l) => l.graded_produce_lot_id}
        renderItem={(l) => (
          <div className="flex flex-wrap items-center justify-between gap-2">
            <Link
              href={`/farms/${farmId}/processing/graded-lots/${l.graded_produce_lot_id}`}
              className="font-medium text-ink hover:underline"
            >
              {l.code}
            </Link>
            <span className="text-ink-muted">
              {l.original_received_weight_kg} kg — {fmtTime(l.effective_time)}
              {l.is_affected_source && (
                <span className="ml-2 rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-900">
                  Source of this trace
                </span>
              )}
            </span>
          </div>
        )}
      />

      <TraceListSection
        title="Packing consumption"
        items={packingInputs}
        keyFor={(l) => l.packing_input_line_id}
        emptyLabel="No Graded Produce Lot in this trace has been packed yet."
        renderItem={(l) => (
          <span className="text-ink-muted">Consumed {l.consumed_weight_kg} kg into a Packing event</span>
        )}
      />

      <TraceListSection
        title="Finished Goods Lots"
        items={finishedGoods}
        keyFor={(l) => l.finished_goods_lot_id}
        renderItem={(l) => (
          <div className="flex flex-wrap items-center justify-between gap-2">
            <Link
              href={`/farms/${farmId}/processing/finished-goods/${l.finished_goods_lot_id}`}
              className="font-medium text-ink hover:underline"
            >
              {l.code}
            </Link>
            <span className="text-ink-muted">
              {l.net_packed_weight_kg} kg / {l.package_count} pkg — available {l.available_weight_kg} kg
            </span>
          </div>
        )}
      />

      <TraceListSection
        title="Cold storage"
        items={storage}
        keyFor={(l) => l.location_id}
        emptyLabel="Nothing from this trace is currently placed in Cold Storage."
        renderItem={(l) => {
          const label = locationLabelById?.get(l.location_id);
          return (
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className={label ? "text-ink" : "font-mono text-ink-muted"}>{label ?? `${l.location_id.slice(0, 8)}…`}</span>
              <span className="text-ink-muted">{l.weight_kg} kg / {l.package_count} pkg</span>
            </div>
          );
        }}
      />

      <TraceListSection
        title="Dispatches"
        items={dispatches}
        keyFor={(l) => l.dispatch_line_id}
        emptyLabel="Nothing from this trace has been dispatched yet."
        renderItem={(l) => (
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="font-medium text-ink">{l.dispatch_event_code}</span>
            <span className="text-ink-muted">
              {l.dispatched_weight_kg} kg / {l.dispatched_package_count} pkg — {fmtTime(l.effective_time)}
            </span>
          </div>
        )}
      />
    </div>
  );
}
