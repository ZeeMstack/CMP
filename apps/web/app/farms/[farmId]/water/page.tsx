"use client";

import Link from "next/link";
import { useParams } from "next/navigation";

import { Breadcrumbs } from "@/components/Breadcrumbs";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { LoadingSkeleton } from "@/components/LoadingSkeleton";
import { PageHeader } from "@/components/PageHeader";
import { StatusBadge } from "@/components/StatusBadge";
import {
  tableBodyDividerClass, tableRowHoverClass, tableTdClass, tableWrapperClass,
} from "@/components/ui/table";
import { WaterSubNav } from "@/components/water/WaterSubNav";
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
import type { IrrigationCircuitRead, ReservoirRead, WaterSourceRead } from "@/lib/api/client";
import type { UseQueryResult } from "@tanstack/react-query";

function statusTone(status: string): "active" | "closed" | "neutral" {
  if (status === "active") return "active";
  if (status === "retired" || status === "closed" || status === "inactive") return "closed";
  return "neutral";
}

/** One count-and-list card for a farm-wide entity collection. Loading, error
 * and empty are each their own state -- an error never renders as "0
 * configured" (LOADING != EMPTY, ERROR != EMPTY). */
function FactCard<T extends { id: string; code: string; name: string; status: string }>({
  title, query, href, hrefLabel, renderExtra,
}: {
  title: string;
  query: UseQueryResult<T[]>;
  href: string;
  hrefLabel: string;
  renderExtra?: (row: T) => string | null;
}) {
  const rows = query.data ?? [];
  const activeCount = rows.filter((r) => r.status === "active").length;

  return (
    <div className="flex flex-col gap-2 rounded-xl border border-wl-border bg-wl-surface-raised p-4">
      <div className="flex items-baseline justify-between gap-2">
        <h2 className="text-sm font-medium text-wl-text-secondary">{title}</h2>
        <Link href={href} className="text-xs font-medium text-wl-brand hover:underline">
          {hrefLabel}
        </Link>
      </div>

      {query.isLoading && !query.data ? (
        <LoadingSkeleton rows={2} label={`Loading ${title}`} />
      ) : query.isError && !query.data ? (
        <ErrorState error={query.error} onRetry={() => query.refetch()} />
      ) : rows.length === 0 ? (
        <p className="text-sm text-wl-text-tertiary">None configured yet.</p>
      ) : (
        <>
          <p className="text-2xl font-semibold text-wl-text">
            {activeCount} <span className="text-sm font-normal text-wl-text-tertiary">active of {rows.length}</span>
          </p>
          <ul className="flex flex-col gap-1">
            {rows.slice(0, 5).map((row) => (
              <li key={row.id} className="flex items-center justify-between gap-2 text-sm">
                <span className="truncate text-wl-text">
                  {row.code} — {row.name}
                  {renderExtra?.(row) ? <span className="text-wl-text-tertiary"> · {renderExtra(row)}</span> : null}
                </span>
                <StatusBadge label={humanizeEnumCode(row.status)} tone={statusTone(row.status)} />
              </li>
            ))}
          </ul>
          {rows.length > 5 && <p className="text-xs text-wl-text-tertiary">+{rows.length - 5} more — see {hrefLabel}</p>}
          {query.isError && <p className="text-xs text-wl-flag-fg">Could not refresh — showing previously loaded data.</p>}
        </>
      )}
    </div>
  );
}

/** PILOT-WATER-001B: Water & Nutrients workspace overview -- compact
 * operator facts (what sources/tanks/circuits exist and their state, latest
 * activity), never a KPI dashboard and never an aggregate readiness score.
 * Multiple Water Sources and multiple Reservoirs/Tanks are the expected
 * normal shape of a farm, not an edge case -- this page never assumes
 * exactly one of either. */
export default function WaterOverviewPage() {
  const { farmId } = useParams<{ farmId: string }>();
  const { data: farm } = useFarm(farmId);

  const sourcesQuery = useWaterSources(farmId);
  const reservoirsQuery = useReservoirs(farmId);
  const circuitsQuery = useIrrigationCircuits(farmId);
  const measurementsQuery = useMeasurementsForFarm(farmId);
  const mixesQuery = useMixesForFarm(farmId);
  const deliveriesQuery = useDeliveryEventsForFarm(farmId);
  const attentionQuery = useWaterAttention(farmId);

  const recentMeasurements = [...(measurementsQuery.data ?? [])]
    .sort((a, b) => new Date(b.effective_at).getTime() - new Date(a.effective_at).getTime())
    .slice(0, 8);
  const recentMixes = [...(mixesQuery.data ?? [])]
    .sort((a, b) => new Date(b.effective_at).getTime() - new Date(a.effective_at).getTime())
    .slice(0, 5);
  const recentDeliveries = [...(deliveriesQuery.data ?? [])]
    .sort((a, b) => new Date(b.effective_start).getTime() - new Date(a.effective_start).getTime())
    .slice(0, 5);

  return (
    <div>
      <PageHeader
        title="Water & Nutrients"
        description={farm ? `Water and nutrient operations for ${farm.name}` : "Water and nutrient operations"}
        breadcrumbs={
          <Breadcrumbs items={[{ label: "Home", href: `/farms/${farmId}` }, { label: "Water & Nutrients" }]} />
        }
      />
      <WaterSubNav farmId={farmId} />

      <section className="grid grid-cols-1 gap-4 md:grid-cols-3">
        <FactCard<WaterSourceRead>
          title="Water Sources"
          query={sourcesQuery}
          href={`/farms/${farmId}/water/setup`}
          hrefLabel="Manage in Setup"
          renderExtra={(row) => humanizeEnumCode(row.source_type)}
        />
        <FactCard<ReservoirRead>
          title="Reservoirs / Tanks"
          query={reservoirsQuery}
          href={`/farms/${farmId}/water/setup`}
          hrefLabel="Manage in Setup"
          renderExtra={(row) => humanizeEnumCode(row.reservoir_type)}
        />
        <FactCard<IrrigationCircuitRead>
          title="Irrigation Circuits"
          query={circuitsQuery}
          href={`/farms/${farmId}/water/setup`}
          hrefLabel="Manage in Setup"
          renderExtra={(row) => humanizeEnumCode(row.system_type ?? "")}
        />
      </section>

      <section className="mt-5 flex flex-col gap-2">
        <div className="flex items-baseline justify-between gap-2">
          <h2 className="font-serif text-base font-semibold text-wl-text">Water Attention</h2>
          <Link href={`/farms/${farmId}`} className="text-xs font-medium text-wl-brand hover:underline">
            View on Today on the Farm
          </Link>
        </div>
        {attentionQuery.isLoading && !attentionQuery.data ? (
          <LoadingSkeleton rows={2} label="Loading Water Attention" />
        ) : attentionQuery.isError && !attentionQuery.data ? (
          <ErrorState error={attentionQuery.error} onRetry={() => attentionQuery.refetch()} />
        ) : (attentionQuery.data ?? []).length === 0 ? (
          <p className="rounded-xl border border-wl-border bg-wl-surface-raised p-4 text-sm text-wl-text">
            Nothing currently needs Water attention.
          </p>
        ) : (
          <ul className="flex flex-col gap-2">
            {(attentionQuery.data ?? []).map((item, i) => (
              <li
                key={`${item.kind}-${i}`}
                className="rounded-lg border border-wl-border-strong bg-wl-hold-bg px-3 py-2 text-sm text-wl-hold-fg"
              >
                {item.message}
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="mt-5 grid grid-cols-1 gap-4 lg:grid-cols-3">
        <div className="flex flex-col gap-2">
          <div className="flex items-baseline justify-between gap-2">
            <h2 className="text-sm font-medium text-wl-text-secondary">Latest Measurements</h2>
            <Link href={`/farms/${farmId}/water/measurements`} className="text-xs font-medium text-wl-brand hover:underline">
              Record / View history
            </Link>
          </div>
          {measurementsQuery.isLoading && !measurementsQuery.data ? (
            <LoadingSkeleton rows={3} label="Loading measurements" />
          ) : measurementsQuery.isError && !measurementsQuery.data ? (
            <ErrorState error={measurementsQuery.error} onRetry={() => measurementsQuery.refetch()} />
          ) : recentMeasurements.length === 0 ? (
            <EmptyState title="No measurements recorded yet" />
          ) : (
            <div className={tableWrapperClass}>
              <table className="w-full text-sm">
                <tbody className={tableBodyDividerClass}>
                  {recentMeasurements.map((m) => (
                    <tr key={m.id} className={tableRowHoverClass}>
                      <td className={tableTdClass}>
                        <div className="font-medium text-wl-text">{humanizeEnumCode(m.metric)}</div>
                        <div className="text-xs text-wl-text-tertiary">{formatDateTimeWithZoneLabel(m.effective_at)}</div>
                      </td>
                      <td className={`${tableTdClass} text-right tabular-nums`}>
                        {m.value} {m.unit}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        <div className="flex flex-col gap-2">
          <div className="flex items-baseline justify-between gap-2">
            <h2 className="text-sm font-medium text-wl-text-secondary">Recent Mixes</h2>
            <Link href={`/farms/${farmId}/water/mixing`} className="text-xs font-medium text-wl-brand hover:underline">
              Record a Mix
            </Link>
          </div>
          {mixesQuery.isLoading && !mixesQuery.data ? (
            <LoadingSkeleton rows={3} label="Loading mixes" />
          ) : mixesQuery.isError && !mixesQuery.data ? (
            <ErrorState error={mixesQuery.error} onRetry={() => mixesQuery.refetch()} />
          ) : recentMixes.length === 0 ? (
            <EmptyState title="No mixes recorded yet" />
          ) : (
            <div className={tableWrapperClass}>
              <table className="w-full text-sm">
                <tbody className={tableBodyDividerClass}>
                  {recentMixes.map((mix) => (
                    <tr key={mix.id} className={tableRowHoverClass}>
                      <td className={tableTdClass}>
                        <div className="font-medium text-wl-text">
                          {mix.actual_volume ? `${mix.actual_volume} vol` : "Volume not recorded"}
                        </div>
                        <div className="text-xs text-wl-text-tertiary">{formatDateTimeWithZoneLabel(mix.effective_at)}</div>
                      </td>
                      <td className={`${tableTdClass} text-right text-xs text-wl-text-tertiary`}>
                        {mix.nutrient_recipe_version_id ? "Recipe-based" : "No recipe reference"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        <div className="flex flex-col gap-2">
          <div className="flex items-baseline justify-between gap-2">
            <h2 className="text-sm font-medium text-wl-text-secondary">Recent Deliveries</h2>
            <Link href={`/farms/${farmId}/water/delivery`} className="text-xs font-medium text-wl-brand hover:underline">
              Record a Delivery
            </Link>
          </div>
          {deliveriesQuery.isLoading && !deliveriesQuery.data ? (
            <LoadingSkeleton rows={3} label="Loading deliveries" />
          ) : deliveriesQuery.isError && !deliveriesQuery.data ? (
            <ErrorState error={deliveriesQuery.error} onRetry={() => deliveriesQuery.refetch()} />
          ) : recentDeliveries.length === 0 ? (
            <EmptyState title="No deliveries recorded yet" />
          ) : (
            <div className={tableWrapperClass}>
              <table className="w-full text-sm">
                <tbody className={tableBodyDividerClass}>
                  {recentDeliveries.map((d) => (
                    <tr key={d.id} className={tableRowHoverClass}>
                      <td className={tableTdClass}>
                        <div className="font-medium text-wl-text">
                          {d.delivered_volume ? `${d.delivered_volume} delivered` : "Volume not measured"}
                        </div>
                        <div className="text-xs text-wl-text-tertiary">
                          {formatDateTimeWithZoneLabel(d.effective_start)}
                          {d.effective_end ? ` – ${formatDateTimeWithZoneLabel(d.effective_end)}` : " – ongoing"}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </section>

      <section className="mt-6 flex flex-wrap gap-2 border-t border-wl-border pt-4">
        <p className="text-xs text-wl-text-tertiary">
          A Water Source may feed multiple Reservoirs; a Reservoir/Tank may serve multiple Circuits and Locations.
          See <Link href={`/farms/${farmId}/water/setup`} className="font-medium text-wl-brand hover:underline">System Setup</Link> for
          current and historical topology connections.
        </p>
      </section>
    </div>
  );
}
