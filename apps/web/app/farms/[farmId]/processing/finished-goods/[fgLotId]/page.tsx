"use client";

import Link from "next/link";
import { useParams } from "next/navigation";

import { Breadcrumbs } from "@/components/Breadcrumbs";
import { ErrorState } from "@/components/ErrorState";
import { LoadingSkeleton } from "@/components/LoadingSkeleton";
import { PageHeader } from "@/components/PageHeader";
import { findOpenRecallCase, RecallBadge } from "@/components/processing/RecallBadge";
import {
  useFinishedGoodsBalance, useFinishedGoodsLedger, useFinishedGoodsLot, useFinishedGoodsPlacement, useRecallCases,
} from "@/lib/query/hooks";

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
        <dl className="grid grid-cols-2 gap-x-4 gap-y-2 rounded-lg border border-border-subtle bg-surface p-4 text-sm sm:grid-cols-3">
          <div>
            <dt className="text-ink-muted">Crop / Variety</dt>
            <dd className="text-ink">
              {lot.crop.common_name}
              {lot.variety ? ` / ${lot.variety.name}` : ""}
            </dd>
          </div>
          <div>
            <dt className="text-ink-muted">Net packed</dt>
            <dd className="text-ink">
              {lot.net_packed_weight_kg} kg / {lot.package_count} packages
            </dd>
          </div>
          <div>
            <dt className="text-ink-muted">Available</dt>
            <dd className="text-ink">
              {balanceQuery.data
                ? `${balanceQuery.data.available_weight_kg} kg / ${balanceQuery.data.available_package_count} pkg`
                : balanceQuery.isLoading
                  ? "Loading…"
                  : "—"}
            </dd>
          </div>
          <div>
            <dt className="text-ink-muted">Effective time</dt>
            <dd className="text-ink">{new Date(lot.effective_time).toLocaleString()}</dd>
          </div>
          <div className="sm:col-span-3">
            <dt className="text-ink-muted">Source Graded Produce Lots</dt>
            <dd className="flex flex-wrap gap-2 text-ink">
              {lot.source_graded_produce_lot_ids.map((gplId) => (
                <Link
                  key={gplId}
                  href={`/farms/${farmId}/processing/graded-lots/${gplId}`}
                  className="rounded-full border border-border-subtle px-2 py-0.5 text-xs hover:bg-surface-subtle"
                >
                  {gplId.slice(0, 8)}
                </Link>
              ))}
            </dd>
          </div>
        </dl>

        <div>
          <h2 className="mb-2 text-sm font-semibold text-ink">Cold-store placement</h2>
          {placementQuery.isLoading && <LoadingSkeleton rows={2} label="Loading placement" />}
          {placementQuery.data && (
            <div className="rounded-lg border border-border-subtle bg-surface p-4 text-sm">
              <p className="text-ink-muted">
                Unplaced: <span className="text-ink">{placementQuery.data.unplaced_weight_kg} kg / {placementQuery.data.unplaced_package_count} pkg</span>
              </p>
              {placementQuery.data.locations.length === 0 ? (
                <p className="mt-2 text-ink-muted">Not yet placed in any cold-store Location.</p>
              ) : (
                <ul className="mt-2 flex flex-col divide-y divide-border-subtle">
                  {placementQuery.data.locations.map((loc) => (
                    <li key={loc.location_id} className="flex items-center justify-between py-1.5">
                      <span className="text-ink-muted">{loc.location_id.slice(0, 8)}</span>
                      <span className="text-ink">{loc.weight_kg} kg / {loc.package_count} pkg</span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </div>

        <div>
          <h2 className="mb-2 text-sm font-semibold text-ink">Ledger</h2>
          {ledgerQuery.isLoading && <LoadingSkeleton rows={2} label="Loading ledger" />}
          {ledgerQuery.data && ledgerQuery.data.length === 0 && (
            <p className="text-sm text-ink-muted">No ledger entries yet.</p>
          )}
          {ledgerQuery.data && ledgerQuery.data.length > 0 && (
            <ul className="flex flex-col divide-y divide-border-subtle rounded-lg border border-border-subtle bg-surface text-sm">
              {ledgerQuery.data.map((entry) => (
                <li key={entry.id} className="flex flex-wrap items-center justify-between gap-2 p-3">
                  <span className="text-ink">
                    {entry.entry_kind === "packing_receipt" ? "Packing receipt" : entry.entry_kind}
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
