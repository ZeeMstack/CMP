"use client";

import { useParams } from "next/navigation";
import { useMemo, useState } from "react";

import { Breadcrumbs } from "@/components/Breadcrumbs";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { LoadingSkeleton } from "@/components/LoadingSkeleton";
import { PageHeader } from "@/components/PageHeader";
import { ResponsiveBatchList } from "@/components/ResponsiveBatchList";
import { useCropBatches, useFarm } from "@/lib/query/hooks";

export default function CropBatchesPage() {
  const { farmId } = useParams<{ farmId: string }>();
  const { data: farm } = useFarm(farmId);
  const { data, isLoading, error, refetch } = useCropBatches(farmId);
  const [search, setSearch] = useState("");
  const [stage, setStage] = useState("");
  const [state, setState] = useState("");

  const stages = useMemo(
    () => [...new Set((data ?? []).map((b) => b.current_stage.name))].sort(),
    [data],
  );
  const states = useMemo(() => [...new Set((data ?? []).map((b) => b.state))].sort(), [data]);

  const filtered = useMemo(() => {
    if (!data) return [];
    const query = search.trim().toLowerCase();
    return data.filter((batch) => {
      if (stage && batch.current_stage.name !== stage) return false;
      if (state && batch.state !== state) return false;
      if (query && !batch.code.toLowerCase().includes(query) && !batch.crop.common_name.toLowerCase().includes(query)) {
        return false;
      }
      return true;
    });
  }, [data, search, stage, state]);

  return (
    <div>
      <PageHeader
        title="Crop batches"
        breadcrumbs={
          <Breadcrumbs items={[{ label: "Home", href: `/farms/${farmId}` }, { label: "Batches" }]} />
        }
      />

      {isLoading && <LoadingSkeleton rows={6} label="Loading crop batches" />}
      {error && <ErrorState error={error} onRetry={() => refetch()} />}

      {data && data.length === 0 && (
        <EmptyState title="No crop batches yet" description="This farm has no crop batches recorded." />
      )}

      {data && data.length > 0 && (
        <>
          <div className="mb-4 flex flex-col gap-2 sm:flex-row sm:items-center">
            <input
              type="search"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search code or crop…"
              aria-label="Search batches"
              className="min-h-11 flex-1 rounded-md border border-border-subtle px-3 text-sm focus-visible:outline focus-visible:outline-2 focus-visible:outline-brand-600"
            />
            <select
              value={stage}
              onChange={(e) => setStage(e.target.value)}
              aria-label="Filter by stage"
              className="min-h-11 rounded-md border border-border-subtle px-3 text-sm"
            >
              <option value="">All stages</option>
              {stages.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
            <select
              value={state}
              onChange={(e) => setState(e.target.value)}
              aria-label="Filter by state"
              className="min-h-11 rounded-md border border-border-subtle px-3 text-sm"
            >
              <option value="">All states</option>
              {states.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </div>

          {filtered.length === 0 ? (
            <EmptyState title="No matching batches" description="Try a different search or filter." />
          ) : (
            <ResponsiveBatchList batches={filtered} farmId={farmId} farmTimezone={farm?.timezone} />
          )}
        </>
      )}
    </div>
  );
}
