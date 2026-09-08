"use client";

import { useParams } from "next/navigation";
import { useState } from "react";

import { Breadcrumbs } from "@/components/Breadcrumbs";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { LoadingSkeleton } from "@/components/LoadingSkeleton";
import { PageHeader } from "@/components/PageHeader";
import { useVinesProductionPlacementGrowBags, useVinesProductionPlacements } from "@/lib/query/hooks";

/** VINES-OPS-001B: the compact Vines Production read view -- one aggregated
 * row per (Batch, Grow Gutter), never one row per plant/Grow Bag. Drill-down
 * shows individual Grow Bags plus their Grow Cube/Seed Tray lineage. */
export default function VinesProductionPage() {
  const { farmId } = useParams<{ farmId: string }>();
  const placementsQuery = useVinesProductionPlacements(farmId);
  const [expanded, setExpanded] = useState<{ batchId: string; gutterId: string } | null>(null);

  return (
    <div>
      <PageHeader
        title="Vines Production"
        breadcrumbs={
          <Breadcrumbs
            items={[
              { label: "Home", href: `/farms/${farmId}` },
              { label: "Vines Production" },
            ]}
          />
        }
      />

      {placementsQuery.isLoading && <LoadingSkeleton rows={4} label="Loading Vines Production placements" />}
      {placementsQuery.isError && <ErrorState error={placementsQuery.error} onRetry={() => placementsQuery.refetch()} />}
      {placementsQuery.isSuccess && (placementsQuery.data ?? []).length === 0 && (
        <EmptyState
          title="Nothing is currently in Vines Production."
          description="Plants appear here once a Transfer to Production has placed living plants in a Grow Gutter."
        />
      )}
      {placementsQuery.isSuccess && (placementsQuery.data ?? []).length > 0 && (
        <div className="overflow-x-auto rounded-xl border border-border-subtle bg-surface">
          <table className="w-full min-w-[720px] text-left text-sm">
            <thead>
              <tr className="border-b border-border-subtle text-ink-muted">
                <th className="p-3 font-medium">Batch</th>
                <th className="p-3 font-medium">Crop</th>
                <th className="p-3 font-medium">Variety</th>
                <th className="p-3 font-medium">Greenhouse</th>
                <th className="p-3 font-medium">Gutter</th>
                <th className="p-3 font-medium">Plants</th>
                <th className="p-3 font-medium">Days in Production</th>
                <th className="p-3 font-medium" />
              </tr>
            </thead>
            <tbody>
              {(placementsQuery.data ?? []).map((row) => {
                const key = `${row.batch_id}:${row.gutter_id}`;
                const isExpanded = expanded?.batchId === row.batch_id && expanded?.gutterId === row.gutter_id;
                return (
                  <>
                    <tr key={key} className="border-b border-border-subtle last:border-0">
                      <td className="p-3 text-ink">{row.batch_code}</td>
                      <td className="p-3 text-ink">{row.crop_common_name}</td>
                      <td className="p-3 text-ink">{row.variety_name ?? "—"}</td>
                      <td className="p-3 text-ink">{row.greenhouse_code}</td>
                      <td className="p-3 text-ink">{row.gutter_code}</td>
                      <td className="p-3 text-ink">{row.plant_count.toLocaleString()}</td>
                      <td className="p-3 text-ink">{row.days_in_production}</td>
                      <td className="p-3">
                        <button
                          type="button"
                          onClick={() => setExpanded(isExpanded ? null : { batchId: row.batch_id, gutterId: row.gutter_id })}
                          className="min-h-9 rounded-md border border-border-subtle px-3 text-xs font-medium text-ink hover:bg-surface-subtle"
                        >
                          {isExpanded ? "Hide Grow Bags" : "Grow Bags"}
                        </button>
                      </td>
                    </tr>
                    {isExpanded && (
                      <tr key={`${key}-detail`} className="border-b border-border-subtle bg-surface-subtle last:border-0">
                        <td colSpan={8} className="p-3">
                          <GrowBagDrillDown farmId={farmId} batchId={row.batch_id} gutterId={row.gutter_id} />
                        </td>
                      </tr>
                    )}
                  </>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function GrowBagDrillDown({ farmId, batchId, gutterId }: { farmId: string; batchId: string; gutterId: string }) {
  const detailQuery = useVinesProductionPlacementGrowBags(farmId, batchId, gutterId);
  if (detailQuery.isLoading) return <p className="text-xs text-ink-muted">Loading Grow Bags…</p>;
  const bags = detailQuery.data ?? [];
  return (
    <ul className="flex flex-col gap-2">
      {bags.map((bag) => (
        <li key={bag.grow_bag.id} className="rounded-md border border-border-subtle bg-surface p-2 text-xs">
          <div className="font-medium text-ink">
            {bag.grow_bag.code} · {bag.grow_bag_position_code} · {bag.assigned_plant_count.toLocaleString()} plants
          </div>
          <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-ink-muted">
            {bag.grow_cubes.map((c) => (
              <span key={c.grow_cube.id}>
                {c.grow_cube.code}
                {c.source_seed_tray ? ` ← ${c.source_seed_tray.code}` : ""}
              </span>
            ))}
          </div>
        </li>
      ))}
    </ul>
  );
}
