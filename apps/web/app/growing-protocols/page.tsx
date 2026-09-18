"use client";

import { PlusCircle } from "lucide-react";
import Link from "next/link";

import { Breadcrumbs } from "@/components/Breadcrumbs";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { LoadingSkeleton } from "@/components/LoadingSkeleton";
import { PageHeader } from "@/components/PageHeader";
import { StandaloneShell } from "@/components/StandaloneShell";
import { StatusBadge } from "@/components/StatusBadge";
import { Button } from "@/components/ui/Button";
import {
  tableBodyDividerClass,
  tableHeadRowClass,
  tableRowHoverClass,
  tableTdClass,
  tableThClass,
  tableWrapperClass,
} from "@/components/ui/table";
import {
  useCrops,
  useGrowingProtocols,
  useProductionSystems,
  useProtocolActiveVersionMap,
  useVarietiesForCrops,
} from "@/lib/query/hooks";

/** PILOT-AGRO-001B Part 1/13: Growing Protocol administration -- a
 * tenant-wide master-data list (mirrors Workflows' own route shape exactly,
 * see `app/workflows/page.tsx`). Kept secondary to floor operations (Setup,
 * never a Today-on-the-Farm surface). Variety, Season and Active Version are
 * this ticket's own explicit compact-table columns -- resolved via the same
 * bounded `useQueries` reference-catalog fan-out already established by
 * `useGradeVersionLabelMap` (tenant-wide master-data scale, not per-Batch
 * operational scale), never a per-row detail fetch on scroll/interaction. */
export default function GrowingProtocolsPage() {
  const protocolsQuery = useGrowingProtocols();
  const cropsQuery = useCrops();
  const productionSystemsQuery = useProductionSystems();

  const protocols = protocolsQuery.data ?? [];
  const crops = cropsQuery.data ?? [];
  const productionSystems = productionSystemsQuery.data ?? [];

  const { varietyById } = useVarietiesForCrops(Array.from(new Set(protocols.map((p) => p.crop_id))));
  const { activeVersionByProtocolId } = useProtocolActiveVersionMap(protocols.map((p) => p.id));

  const isLoading = protocolsQuery.isLoading || cropsQuery.isLoading || productionSystemsQuery.isLoading;
  const loadError = protocolsQuery.error ?? cropsQuery.error ?? productionSystemsQuery.error;

  return (
    <StandaloneShell>
      <PageHeader
        title="Growing Protocols"
        breadcrumbs={<Breadcrumbs items={[{ label: "Home", href: "/farms" }, { label: "Growing Protocols" }]} />}
        actions={
          <Link href="/growing-protocols/new">
            <Button variant="primary">
              <PlusCircle aria-hidden="true" className="h-4 w-4" />
              New protocol
            </Button>
          </Link>
        }
      />
      <p className="-mt-3 mb-6 text-xs text-wl-text-secondary">
        Tenant-wide agronomic guidance catalog: care/observation expectations a Batch can be assigned once activated.
        Publishing a version here never changes any already-assigned Batch.
      </p>

      {isLoading && <LoadingSkeleton rows={4} label="Loading growing protocols" />}
      {loadError && (
        <ErrorState
          error={loadError}
          onRetry={() => {
            protocolsQuery.refetch();
            cropsQuery.refetch();
            productionSystemsQuery.refetch();
          }}
        />
      )}

      {!isLoading && !loadError && protocols.length === 0 && (
        <EmptyState
          title="No growing protocols yet"
          description="Create the first protocol once at least one crop exists."
        />
      )}

      {!isLoading && !loadError && protocols.length > 0 && (
        <div className={tableWrapperClass}>
          <table className="w-full text-left text-sm">
            <thead>
              <tr className={tableHeadRowClass}>
                <th className={tableThClass}>Code</th>
                <th className={tableThClass}>Name</th>
                <th className={tableThClass}>Crop</th>
                <th className={tableThClass}>Variety</th>
                <th className={tableThClass}>Production system</th>
                <th className={tableThClass}>Season</th>
                <th className={tableThClass}>Active version</th>
                <th className={tableThClass}>Status</th>
                <th className={tableThClass} />
              </tr>
            </thead>
            <tbody className={tableBodyDividerClass}>
              {protocols.map((protocol) => {
                const crop = crops.find((c) => c.id === protocol.crop_id);
                const productionSystem = productionSystems.find((p) => p.id === protocol.production_system_id);
                const variety = protocol.variety_id ? varietyById[protocol.variety_id] : undefined;
                const activeVersion = activeVersionByProtocolId[protocol.id];
                return (
                  <tr key={protocol.id} className={tableRowHoverClass}>
                    <td className={`${tableTdClass} font-medium text-wl-text`}>{protocol.code}</td>
                    <td className={`${tableTdClass} text-wl-text`}>{protocol.name}</td>
                    <td className={`${tableTdClass} text-wl-text-secondary`}>{crop ? crop.common_name : "—"}</td>
                    <td className={`${tableTdClass} text-wl-text-secondary`}>
                      {protocol.variety_id ? (variety ? variety.name : "…") : "Any"}
                    </td>
                    <td className={`${tableTdClass} text-wl-text-secondary`}>
                      {productionSystem ? productionSystem.name : "Any"}
                    </td>
                    <td className={`${tableTdClass} text-wl-text-secondary`}>{protocol.season_context ?? "Any"}</td>
                    <td className={`${tableTdClass} text-wl-text-secondary`}>
                      {activeVersion ? `v${activeVersion.version_number}` : "None active"}
                    </td>
                    <td className={tableTdClass}>
                      <StatusBadge
                        label={protocol.status === "active" ? "Active" : "Inactive"}
                        tone={protocol.status === "active" ? "active" : "closed"}
                      />
                    </td>
                    <td className={tableTdClass}>
                      <Link
                        href={`/growing-protocols/${protocol.id}`}
                        className="text-sm font-medium text-wl-brand hover:underline"
                      >
                        Open
                      </Link>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </StandaloneShell>
  );
}
