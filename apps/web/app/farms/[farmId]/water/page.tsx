"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import type { ReactNode } from "react";

import { LoadingSkeleton } from "@/components/LoadingSkeleton";
import { QueueSourceFailureRow } from "@/components/layout/QueueRow";
import { WaterWorkspaceHeader, entityLabel, linkButtonClass, metricLabel } from "@/components/water/waterUi";
import { formatDateTimeWithZoneLabel } from "@/lib/format/datetime";
import { humanizeEnumCode } from "@/lib/format/humanize";
import {
  useDeliveryEventsForFarm,
  useFarm,
  useIrrigationCircuits,
  useMeasurementsForFarm,
  useMixesForFarm,
  useReservoirs,
  useWaterAttention,
  useWaterSources,
} from "@/lib/query/hooks";
import type { UseQueryResult } from "@tanstack/react-query";

const RECENT_LIMIT = 5;

/** One bounded source panel with its OWN loading / unavailable / empty
 * states -- a failed read is shown as unavailable, never as "nothing" or
 * zero, and never hides a sibling source. */
function SourcePanel<T>({
  title,
  query,
  emptyText,
  href,
  hrefLabel,
  render,
}: {
  title: string;
  query: UseQueryResult<T[]>;
  emptyText: string;
  href?: string;
  hrefLabel?: string;
  render: (rows: T[]) => ReactNode;
}) {
  const rows = query.data ?? [];
  return (
    <section aria-label={title} className="flex min-w-0 flex-col gap-2 rounded-xl border border-wl-border bg-wl-surface-raised p-3">
      <div className="flex items-baseline justify-between gap-2">
        <h2 className="text-sm font-semibold text-wl-text">{title}</h2>
        {href && (
          <Link href={href} className="text-xs font-medium text-wl-brand hover:underline">
            {hrefLabel}
          </Link>
        )}
      </div>
      {query.isLoading && !query.data ? (
        <LoadingSkeleton rows={2} label={`Loading ${title}`} />
      ) : query.isError && !query.data ? (
        <QueueSourceFailureRow sourceLabel={title} message="could not be loaded." onRetry={() => void query.refetch()} />
      ) : rows.length === 0 ? (
        <p className="text-sm text-wl-text-secondary">{emptyText}</p>
      ) : (
        <>
          {render(rows)}
          {query.isError && <p className="text-xs text-wl-text-tertiary">Could not refresh — showing previously loaded data.</p>}
        </>
      )}
    </section>
  );
}

function TopologyLine<T extends { id: string; code: string; name: string; status: string }>({
  label, query,
}: {
  label: string;
  query: UseQueryResult<T[]>;
}) {
  if (query.isLoading && !query.data) return <li>{label}: loading…</li>;
  if (query.isError && !query.data) return <li>{label}: unavailable</li>;
  const rows = query.data ?? [];
  const active = rows.filter((r) => r.status === "active");
  return (
    <li>
      <span className="font-medium text-wl-text">{label}:</span>{" "}
      {rows.length === 0
        ? "none configured"
        : `${active.length} active of ${rows.length} — ${active.slice(0, 4).map((r) => r.code).join(", ")}${active.length > 4 ? ", …" : ""}`}
    </li>
  );
}

/** UX-OPS-001D: Water hub -- direct actions first, then attention and
 * ongoing deliveries that need a next action, then bounded recent
 * activity; topology/setup is supporting context, last. Never a KPI
 * dashboard, readiness score, or singular source/tank assumption. */
export default function WaterOverviewPage() {
  const { farmId } = useParams<{ farmId: string }>();
  const { data: farm } = useFarm(farmId);

  const attentionQuery = useWaterAttention(farmId);
  const deliveriesQuery = useDeliveryEventsForFarm(farmId);
  const measurementsQuery = useMeasurementsForFarm(farmId);
  const mixesQuery = useMixesForFarm(farmId);
  const sourcesQuery = useWaterSources(farmId);
  const reservoirsQuery = useReservoirs(farmId);
  const circuitsQuery = useIrrigationCircuits(farmId);

  const reservoirLabel = (id: string) =>
    entityLabel((reservoirsQuery.data ?? []).find((r) => r.id === id)) ?? "Reservoir label unavailable";
  const circuitLabel = (id: string) =>
    entityLabel((circuitsQuery.data ?? []).find((c) => c.id === id)) ?? "Circuit label unavailable";
  const newestFirst = <T,>(rows: T[], at: (row: T) => string) =>
    [...rows].sort((a, b) => new Date(at(b)).getTime() - new Date(at(a)).getTime());

  // Derived views of the SAME query keep its loading/error state.
  const ongoingQuery = {
    ...deliveriesQuery,
    data: deliveriesQuery.data ? deliveriesQuery.data.filter((d) => d.effective_end === null) : undefined,
  } as typeof deliveriesQuery;

  return (
    <div>
      <WaterWorkspaceHeader
        farmId={farmId}
        title="Water & Nutrients"
        description={farm ? `Water and nutrient operations for ${farm.name}` : undefined}
      />

      <nav aria-label="Water actions" className="mb-4 flex flex-wrap gap-2">
        <Link href={`/farms/${farmId}/water/measurements`} className={linkButtonClass}>Record measurements</Link>
        <Link href={`/farms/${farmId}/water/mixing`} className={linkButtonClass}>Record a mix</Link>
        <Link href={`/farms/${farmId}/water/delivery`} className={linkButtonClass}>Delivery</Link>
        <Link href={`/farms/${farmId}/water/exposure`} className={linkButtonClass}>Review exposure</Link>
      </nav>

      <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
        <SourcePanel
          title="Water Attention"
          query={attentionQuery}
          emptyText="Nothing currently needs Water attention."
          href={`/farms/${farmId}`}
          hrefLabel="Today on the Farm"
          render={(items) => (
            <ul className="flex max-h-60 flex-col gap-1.5 overflow-y-auto">
              {items.map((item, i) => (
                <li key={`${item.kind}-${i}`} className="rounded-lg border border-wl-border-strong bg-wl-hold-bg px-3 py-2 text-sm text-wl-hold-fg">
                  <span className="mr-1 text-[10px] font-semibold uppercase tracking-wide">{humanizeEnumCode(item.kind)}</span>
                  {item.message}
                </li>
              ))}
            </ul>
          )}
        />
        <SourcePanel
          title="Ongoing deliveries"
          query={ongoingQuery}
          emptyText="No ongoing deliveries."
          href={`/farms/${farmId}/water/delivery`}
          hrefLabel="All deliveries"
          render={(rows) => (
            <ul className="flex max-h-60 flex-col divide-y divide-wl-border overflow-y-auto">
              {newestFirst(rows, (d) => d.effective_start).map((d) => (
                <li key={d.id} className="flex min-h-11 flex-wrap items-center justify-between gap-2 py-1.5 text-sm">
                  <span className="min-w-0">
                    <span className="font-medium text-wl-text">{reservoirLabel(d.reservoir_id)} → {circuitLabel(d.irrigation_circuit_id)}</span>
                    <span className="block text-xs text-wl-text-secondary">Started {formatDateTimeWithZoneLabel(d.effective_start)} · ongoing</span>
                  </span>
                  <Link
                    href={`/farms/${farmId}/water/delivery?selected=${d.id}&panel=end`}
                    className="inline-flex min-h-11 items-center rounded-md px-2 text-xs font-medium text-wl-brand hover:underline"
                  >
                    End Delivery
                  </Link>
                </li>
              ))}
            </ul>
          )}
        />
      </div>

      <h2 className="mb-2 mt-5 font-serif text-base font-semibold text-wl-text">Recent activity</h2>
      <div className="grid grid-cols-1 gap-3 lg:grid-cols-3">
        <SourcePanel
          title="Measurements"
          query={measurementsQuery}
          emptyText="No measurements recorded yet."
          href={`/farms/${farmId}/water/measurements?view=history`}
          hrefLabel="History"
          render={(rows) => (
            <ul className="flex flex-col divide-y divide-wl-border">
              {newestFirst(rows, (m) => m.effective_at).slice(0, RECENT_LIMIT).map((m) => (
                <li key={m.id} className="flex justify-between gap-2 py-1.5 text-sm">
                  <span>
                    <span className="font-medium text-wl-text">{metricLabel(m.metric)}</span>
                    <span className="block text-xs text-wl-text-secondary">{formatDateTimeWithZoneLabel(m.effective_at)}</span>
                  </span>
                  <span className="tabular-nums">{m.value} {m.unit}</span>
                </li>
              ))}
            </ul>
          )}
        />
        <SourcePanel
          title="Mixes"
          query={mixesQuery}
          emptyText="No mixes recorded yet."
          href={`/farms/${farmId}/water/mixing?view=recent`}
          hrefLabel="Recent mixes"
          render={(rows) => (
            <ul className="flex flex-col divide-y divide-wl-border">
              {newestFirst(rows, (m) => m.effective_at).slice(0, RECENT_LIMIT).map((mix) => (
                <li key={mix.id} className="py-1.5 text-sm">
                  <span className="font-medium text-wl-text">{reservoirLabel(mix.reservoir_id)}</span>
                  <span className="block text-xs text-wl-text-secondary">
                    {formatDateTimeWithZoneLabel(mix.effective_at)} · {mix.nutrient_recipe_version_id ? "Recipe-based" : "No recipe reference"} · Actual {mix.actual_volume ?? "not recorded"}
                  </span>
                </li>
              ))}
            </ul>
          )}
        />
        <SourcePanel
          title="Deliveries"
          query={deliveriesQuery}
          emptyText="No deliveries recorded yet."
          href={`/farms/${farmId}/water/delivery`}
          hrefLabel="Delivery"
          render={(rows) => (
            <ul className="flex flex-col divide-y divide-wl-border">
              {newestFirst(rows, (d) => d.effective_start).slice(0, RECENT_LIMIT).map((d) => (
                <li key={d.id} className="py-1.5 text-sm">
                  <span className="font-medium text-wl-text">{reservoirLabel(d.reservoir_id)} → {circuitLabel(d.irrigation_circuit_id)}</span>
                  <span className="block text-xs text-wl-text-secondary">
                    {formatDateTimeWithZoneLabel(d.effective_start)} – {d.effective_end ? formatDateTimeWithZoneLabel(d.effective_end) : "ongoing"} ·{" "}
                    {d.delivered_volume ? `${d.delivered_volume} delivered` : "Not measured"}
                  </span>
                </li>
              ))}
            </ul>
          )}
        />
      </div>

      <section aria-label="Configured topology" className="mt-5 flex flex-col gap-1 border-t border-wl-border pt-3 text-xs text-wl-text-secondary">
        <h2 className="text-sm font-semibold text-wl-text">Configured topology (supporting context)</h2>
        <ul className="flex flex-col gap-0.5">
          <TopologyLine label="Water Sources" query={sourcesQuery} />
          <TopologyLine label="Reservoirs / Tanks" query={reservoirsQuery} />
          <TopologyLine label="Irrigation Circuits" query={circuitsQuery} />
        </ul>
        <p>
          A farm may have many sources, tanks, and circuits; a source may feed several tanks and a tank several circuits.{" "}
          <Link href={`/farms/${farmId}/water/setup`} className="font-medium text-wl-brand hover:underline">System Setup</Link>{" "}
          holds current and historical connections.
        </p>
      </section>
    </div>
  );
}
