"use client";

import { PlusCircle } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useMemo, useState } from "react";

import { Breadcrumbs } from "@/components/Breadcrumbs";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { BoundedDataRegion } from "@/components/layout/BoundedDataRegion";
import { QueueList, QueueRow } from "@/components/layout/QueueRow";
import { SplitWorkspace } from "@/components/layout/SplitWorkspace";
import { LoadingSkeleton } from "@/components/LoadingSkeleton";
import { SeedLotInspector } from "@/components/nursery/SeedLotInspector";
import { PageHeader } from "@/components/PageHeader";
import { useSeedLots } from "@/lib/query/hooks";

export default function SeedLotsPage() {
  const { farmId } = useParams<{ farmId: string }>();
  const { data, isLoading, error, refetch } = useSeedLots(farmId);
  const [search, setSearch] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const rows = data ?? [];
  const filteredRows = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return data ?? [];
    return (data ?? []).filter(
      (lot) =>
        lot.code.toLowerCase().includes(q) ||
        lot.crop.common_name.toLowerCase().includes(q) ||
        lot.variety.name.toLowerCase().includes(q) ||
        (lot.supplier_name ?? "").toLowerCase().includes(q),
    );
  }, [data, search]);
  const selectedLot = filteredRows.find((l) => l.id === selectedId) ?? null;

  return (
    <div>
      <PageHeader
        title="Seed Lots"
        compact
        breadcrumbs={<Breadcrumbs items={[{ label: "Home", href: `/farms/${farmId}` }, { label: "Seed Lots" }]} />}
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <Link
              href={`/farms/${farmId}/nursery/sowings/new`}
              className="flex min-h-11 items-center gap-1.5 rounded-md border border-wl-border bg-wl-surface-raised px-3 text-sm font-medium text-wl-text hover:bg-wl-surface-hover focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-wl-focus"
            >
              Go to Seeding
            </Link>
            <Link
              href={`/farms/${farmId}/seed-lots/new`}
              className="flex min-h-11 items-center gap-1.5 rounded-md bg-wl-brand px-3 text-sm font-medium text-wl-text-on-brand hover:bg-wl-brand-hover focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-wl-focus"
            >
              <PlusCircle aria-hidden="true" className="h-4 w-4" />
              Add Seed Lot
            </Link>
          </div>
        }
      />
      <p className="mb-4 text-xs text-wl-text-secondary">
        A Seed Lot records where the seed for a Sowing came from — a traceability source, not seed stock on hand.
        Not shown in the main menu, but reachable here and from Seeding whenever a Sowing needs one.
      </p>
      {isLoading && <LoadingSkeleton rows={4} label="Loading Seed Lots" />}
      {error && <ErrorState error={error} onRetry={() => refetch()} />}
      {data && rows.length === 0 && (
        <EmptyState
          title="No Seed Lots registered yet."
          description="Add your first Seed Lot before sowing a Crop Batch."
          action={
            <Link
              href={`/farms/${farmId}/seed-lots/new`}
              className="mt-2 flex min-h-11 items-center gap-1.5 rounded-md bg-wl-brand px-3 text-sm font-medium text-wl-text-on-brand hover:bg-wl-brand-hover"
            >
              <PlusCircle aria-hidden="true" className="h-4 w-4" />
              Add Seed Lot
            </Link>
          }
        />
      )}
      {data && rows.length > 0 && (
        <>
          <div className="mb-3">
            <label className="flex flex-col gap-1">
              <span className="text-sm font-medium text-wl-text">Search</span>
              <input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Code, crop, variety, or supplier…"
                className="min-h-11 w-full max-w-sm rounded-md border border-wl-border bg-wl-surface-raised px-3 text-sm text-wl-text focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-wl-focus"
              />
            </label>
          </div>
          {filteredRows.length === 0 ? (
            <EmptyState title="No Seed Lots match this search" description="Clear the search to see every Seed Lot." />
          ) : (
            <SplitWorkspace
              main={
                <BoundedDataRegion label="Seed Lot register">
                  <QueueList label="Seed Lot register">
                    {filteredRows.map((lot) => (
                      <QueueRow
                        key={lot.id}
                        isSelected={lot.id === selectedId}
                        onSelect={() => setSelectedId(lot.id)}
                        title={lot.code}
                        context={`${lot.crop.common_name} — ${lot.variety.name}`}
                        meta={lot.supplier_name ?? undefined}
                      />
                    ))}
                  </QueueList>
                </BoundedDataRegion>
              }
              rail={<SeedLotInspector seedLot={selectedLot} farmId={farmId} onClose={() => setSelectedId(null)} />}
            />
          )}
        </>
      )}
    </div>
  );
}
