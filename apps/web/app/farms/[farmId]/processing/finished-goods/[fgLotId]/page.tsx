"use client";

import Link from "next/link";
import { useParams } from "next/navigation";

import { Breadcrumbs } from "@/components/Breadcrumbs";
import { ErrorState } from "@/components/ErrorState";
import { LoadingSkeleton } from "@/components/LoadingSkeleton";
import { PageHeader } from "@/components/PageHeader";
import { findOpenRecallCase, RecallBadge } from "@/components/processing/RecallBadge";
import type { LocationTreeNode } from "@/lib/api/client";
import {
  useFinishedGoodsBalance, useFinishedGoodsLedger, useFinishedGoodsLot, useFinishedGoodsPlacement,
  useGradedProduceLot, useLocationsTree, useRecallCases,
} from "@/lib/query/hooks";

const FG_LEDGER_ENTRY_KIND_LABEL: Record<string, string> = {
  packing_receipt: "Packing receipt",
  dispatch_issue: "Dispatch issue",
  packing_reversal: "Packing reversed",
};

/** Resolves a Location id to its ancestry label using the Farm's already-
 * fetched Locations tree (the same read every other Location picker in this
 * app already uses -- e.g. `LocationSelect.tsx`'s own `flatten`) -- no new
 * endpoint, no per-id fetch. Falls back to the styled raw id only if the
 * Location genuinely isn't in the tree (a gap in current data, not
 * something this page can safely invent a label for). */
function flattenLocationLabels(nodes: LocationTreeNode[], pathPrefix: string[] = []): Map<string, string> {
  const map = new Map<string, string>();
  for (const node of nodes) {
    const path = [...pathPrefix, node.name];
    map.set(node.id, path.join(" / "));
    for (const [id, label] of flattenLocationLabels(node.children, path)) map.set(id, label);
  }
  return map;
}

/** Resolves one source Graded Produce Lot id to its real code via the
 * existing per-Lot read (`useGradedProduceLot`, the same hook the Graded
 * Produce detail page itself uses) -- not a new endpoint, just reused per
 * source id, bounded by however many source Lots this Finished Goods Lot
 * actually has (typically small). Falls back to a clearly-styled truncated
 * id only while loading or if the Lot can't be resolved. */
function SourceGplLink({ farmId, gplId }: { farmId: string; gplId: string }) {
  const gplQuery = useGradedProduceLot(farmId, gplId);
  const label = gplQuery.data?.code ?? `${gplId.slice(0, 8)}…`;
  return (
    <Link
      href={`/farms/${farmId}/processing/graded-lots/${gplId}`}
      className={`rounded-full border border-border-subtle px-2 py-0.5 text-xs hover:bg-surface-subtle ${
        gplQuery.data ? "font-medium text-ink" : "font-mono text-ink-muted"
      }`}
    >
      {label}
    </Link>
  );
}

/** POSTHARVEST-OPS-001G: Finished Goods Lot detail -- net packed weight,
 * source Graded Produce Lots (traceability back one step), current
 * available/placed/unplaced balance, cold-store placement by Location,
 * ledger, and recall status. */
export default function FinishedGoodsLotDetailPage() {
  const { farmId, fgLotId } = useParams<{ farmId: string; fgLotId: string }>();
  const lotQuery = useFinishedGoodsLot(farmId, fgLotId);
  const balanceQuery = useFinishedGoodsBalance(farmId, fgLotId);
  const placementQuery = useFinishedGoodsPlacement(farmId, fgLotId);
  const ledgerQuery = useFinishedGoodsLedger(farmId, fgLotId);
  const recallCasesQuery = useRecallCases(farmId);
  const locationsQuery = useLocationsTree(farmId);
  const locationLabelById = locationsQuery.data ? flattenLocationLabels(locationsQuery.data) : new Map<string, string>();

  if (lotQuery.isLoading) return <LoadingSkeleton rows={4} label="Loading Finished Goods Lot" />;
  if (lotQuery.error) return <ErrorState error={lotQuery.error} onRetry={() => lotQuery.refetch()} />;
  const lot = lotQuery.data;
  if (!lot) return null;

  const recallCase = findOpenRecallCase(recallCasesQuery.data, "finished_goods_lot_id", lot.id);

  return (
    <div>
      <PageHeader
        title={lot.code}
        breadcrumbs={
          <Breadcrumbs
            items={[
              { label: "Home", href: `/farms/${farmId}` },
              { label: "Processing", href: `/farms/${farmId}/processing` },
              { label: "Finished Goods", href: `/farms/${farmId}/processing/finished-goods` },
              { label: lot.code },
            ]}
          />
        }
      />

      <div className="flex flex-col gap-4">
        {recallCase && <RecallBadge recallCase={recallCase} />}
        <dl className="grid grid-cols-2 gap-x-4 gap-y-3 rounded-xl border border-border-subtle bg-surface p-4 text-sm sm:grid-cols-3">
          <div>
            <dt className="text-xs font-medium uppercase tracking-wide text-ink-muted">Crop / Variety</dt>
            <dd className="text-ink">
              {lot.crop.common_name}
              {lot.variety ? ` / ${lot.variety.name}` : ""}
            </dd>
          </div>
          <div>
            {/* Original Packing receipt -- immutable historical fact. */}
            <dt className="text-xs font-medium uppercase tracking-wide text-ink-muted">Original Packing receipt</dt>
            <dd className="text-ink">
              {lot.net_packed_weight_kg} kg / {lot.package_count} packages
            </dd>
          </div>
          <div>
            {/* Current commercial balance -- authoritative, live, and never
                the same figure as the original receipt once any Dispatch/
                Cold Storage activity has happened. */}
            <dt className="text-xs font-medium uppercase tracking-wide text-ink-muted">Current commercial balance</dt>
            <dd className="font-semibold text-ink">
              {balanceQuery.data
                ? `${balanceQuery.data.available_weight_kg} kg / ${balanceQuery.data.available_package_count} pkg`
                : balanceQuery.isLoading
                  ? "Loading…"
                  : "—"}
            </dd>
          </div>
          <div>
            <dt className="text-xs font-medium uppercase tracking-wide text-ink-muted">Effective time</dt>
            <dd className="text-ink">{new Date(lot.effective_time).toLocaleString()}</dd>
          </div>
          <div className="sm:col-span-3">
            <dt className="text-xs font-medium uppercase tracking-wide text-ink-muted">Source Graded Produce Lots</dt>
            <dd className="flex flex-wrap gap-2 text-ink">
              {lot.source_graded_produce_lot_ids.map((gplId) => (
                <SourceGplLink key={gplId} farmId={farmId} gplId={gplId} />
              ))}
            </dd>
          </div>
        </dl>

        <div>
          <h2 className="mb-2 font-serif text-sm font-semibold text-ink">Cold-store placement</h2>
          {placementQuery.isLoading && <LoadingSkeleton rows={2} label="Loading placement" />}
          {placementQuery.data && (
            <div className="rounded-xl border border-border-subtle bg-surface p-4 text-sm">
              {/* Unplaced is its own distinct figure -- weight/packages of
                  this Lot's current balance NOT sitting in any cold-store
                  Location, never merged into "placed" or "available". */}
              <p className="text-ink-muted">
                Unplaced:{" "}
                <span className="font-semibold text-ink">
                  {placementQuery.data.unplaced_weight_kg} kg / {placementQuery.data.unplaced_package_count} pkg
                </span>
              </p>
              {placementQuery.data.locations.length === 0 ? (
                <p className="mt-2 text-ink-muted">Not yet placed in any cold-store Location.</p>
              ) : (
                <ul className="mt-2 flex flex-col divide-y divide-border-subtle">
                  {placementQuery.data.locations.map((loc) => {
                    const label = locationLabelById.get(loc.location_id);
                    return (
                      <li key={loc.location_id} className="flex items-center justify-between py-1.5">
                        <span className={label ? "text-ink-muted" : "font-mono text-ink-muted"}>
                          {label ?? `${loc.location_id.slice(0, 8)}…`}
                        </span>
                        <span className="text-ink">{loc.weight_kg} kg / {loc.package_count} pkg</span>
                      </li>
                    );
                  })}
                </ul>
              )}
            </div>
          )}
        </div>

        <div>
          <h2 className="mb-2 font-serif text-sm font-semibold text-ink">Ledger</h2>
          {ledgerQuery.isLoading && <LoadingSkeleton rows={2} label="Loading ledger" />}
          {ledgerQuery.data && ledgerQuery.data.length === 0 && (
            <p className="text-sm text-ink-muted">No ledger entries yet.</p>
          )}
          {ledgerQuery.data && ledgerQuery.data.length > 0 && (
            <ul className="flex flex-col divide-y divide-border-subtle rounded-xl border border-border-subtle bg-surface text-sm">
              {ledgerQuery.data.map((entry) => (
                <li key={entry.id} className="flex flex-wrap items-center justify-between gap-2 p-3">
                  <span className="text-ink">
                    {FG_LEDGER_ENTRY_KIND_LABEL[entry.entry_kind] ?? entry.entry_kind}
                  </span>
                  <span className="text-ink">
                    {Number(entry.weight_delta_kg) > 0 ? "+" : ""}
                    {entry.weight_delta_kg} kg / {entry.package_count_delta} pkg
                  </span>
                  <span className="text-ink-muted">{new Date(entry.effective_time).toLocaleString()}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}
