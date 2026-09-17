"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useMemo } from "react";

import { Breadcrumbs } from "@/components/Breadcrumbs";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { LoadingSkeleton } from "@/components/LoadingSkeleton";
import { PageHeader } from "@/components/PageHeader";
import { StatusBadge } from "@/components/StatusBadge";
import { humanizeEnumCode } from "@/lib/format/humanize";
import { useAssets, useAwaitingCleaning, useCarriers } from "@/lib/query/hooks";

/** PILOT-ASSET-001: the Cleaning Queue -- deliberately a compact table, not
 * a form-heavy page (per the ticket's own instruction). `EquipmentReadinessStateRead`
 * carries no `code` field, so Asset/Carrier codes are resolved client-side by
 * matching against the farm's already-fetched Asset/Carrier lists, mirroring
 * `CreateWorkItemForm`'s "reuse already-fetched farm data" convention rather
 * than adding a new backend read. */
export default function EquipmentCleaningQueuePage() {
  const { farmId } = useParams<{ farmId: string }>();
  const queueQuery = useAwaitingCleaning(farmId);
  // `assetType=""` lists every Asset type for this farm (mirrors
  // app/farms/[farmId]/page.tsx's own `useAssets(farmId, "")` usage).
  const assetsQuery = useAssets(farmId, "");
  const carriersQuery = useCarriers(farmId);

  const assetCodeById = useMemo(
    () => new Map((assetsQuery.data ?? []).map((a) => [a.id, a.code])),
    [assetsQuery.data],
  );
  const carrierCodeById = useMemo(
    () => new Map((carriersQuery.data ?? []).map((c) => [c.id, c.code])),
    [carriersQuery.data],
  );

  const isLoading = queueQuery.isLoading || assetsQuery.isLoading || carriersQuery.isLoading;
  const loadError = queueQuery.error ?? assetsQuery.error ?? carriersQuery.error;
  const rows = queueQuery.data ?? [];

  return (
    <div>
      <PageHeader
        title="Cleaning Queue"
        description="Equipment awaiting cleaning, and cleaning completed but not yet released to Ready."
        breadcrumbs={
          <Breadcrumbs items={[{ label: "Home", href: `/farms/${farmId}` }, { label: "Cleaning Queue" }]} />
        }
      />

      {isLoading && <LoadingSkeleton rows={4} label="Loading cleaning queue" />}
      {!isLoading && loadError && (
        <ErrorState
          error={loadError}
          onRetry={() => {
            queueQuery.refetch();
            assetsQuery.refetch();
            carriersQuery.refetch();
          }}
        />
      )}
      {!isLoading && !loadError && rows.length === 0 && (
        <EmptyState title="Nothing in the Cleaning Queue" description="No equipment is currently awaiting cleaning or release." />
      )}
      {!isLoading && !loadError && rows.length > 0 && (
        <div className="overflow-x-auto rounded-xl border border-wl-border bg-wl-surface-raised">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-wl-border bg-wl-surface-sunken text-xs uppercase text-wl-text-secondary">
              <tr>
                <th className="px-4 py-2 font-medium">Code</th>
                <th className="px-4 py-2 font-medium">Type</th>
                <th className="px-4 py-2 font-medium">Status</th>
                <th className="px-4 py-2 font-medium" />
              </tr>
            </thead>
            <tbody className="divide-y divide-wl-border">
              {rows.map((row) => {
                const code = row.asset_id ? assetCodeById.get(row.asset_id) : carrierCodeById.get(row.carrier_id ?? "");
                const href = `/farms/${farmId}/equipment/${row.entity_type}/${row.asset_id ?? row.carrier_id}/readiness`;
                return (
                  <tr key={row.id} className="hover:bg-wl-surface-hover">
                    <td className="px-4 py-2 font-medium text-wl-text">{code ?? "—"}</td>
                    <td className="px-4 py-2 text-wl-text-secondary">{humanizeEnumCode(row.entity_type)}</td>
                    <td className="px-4 py-2">
                      <StatusBadge label={humanizeEnumCode(row.current_state)} tone="attention" />
                    </td>
                    <td className="px-4 py-2 text-right">
                      <Link
                        href={row.current_state === "cleaning_completed" ? href : `${href}?action=record-cleaning`}
                        className="text-sm font-medium text-wl-brand hover:underline"
                      >
                        {row.current_state === "cleaning_completed" ? "Mark Ready" : "Record Cleaning"}
                      </Link>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
