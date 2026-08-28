"use client";

import { useParams } from "next/navigation";
import { useState } from "react";

import { Breadcrumbs } from "@/components/Breadcrumbs";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { FilterableSelect } from "@/components/FilterableSelect";
import { LoadingSkeleton } from "@/components/LoadingSkeleton";
import { PageHeader } from "@/components/PageHeader";
import { ColdStorageMovementForm } from "@/components/processing/ColdStorageMovementForm";
import { AppError } from "@/lib/errors/adapter";
import {
  useFinishedGoodsLots, useFinishedGoodsStorageMovements, useLocationsTree, useRecordFinishedGoodsStorageMovement,
} from "@/lib/query/hooks";

function asAppError(error: unknown): AppError {
  return error instanceof AppError ? error : new AppError("server_error", "Something went wrong. Please try again.");
}

/** PILOT-READY-001: the Cold Storage workspace -- pick a Finished Goods
 * Lot, then record a place/transfer/release movement for it, with that
 * Lot's own movement history shown alongside. Closes a confirmed pilot
 * blocker: the backend has always supported Cold Storage placement, but
 * it was previously only readable (never writable) from the frontend. */
export default function ColdStoragePage() {
  const { farmId } = useParams<{ farmId: string }>();
  const [selectedLotId, setSelectedLotId] = useState("");
  const [recordError, setRecordError] = useState<AppError | null>(null);
  const [recordSuccess, setRecordSuccess] = useState(false);

  const lotsQuery = useFinishedGoodsLots(farmId);
  const locationsQuery = useLocationsTree(farmId);
  const movementsQuery = useFinishedGoodsStorageMovements(farmId, selectedLotId || null);
  const recordMutation = useRecordFinishedGoodsStorageMovement(farmId);

  const allLots = lotsQuery.data ?? [];
  const selectedLot = allLots.find((l) => l.id === selectedLotId) ?? null;
  const lotOptions = allLots.map((l) => ({
    value: l.id,
    label: l.code,
    description: `${l.crop.common_name}${l.variety ? ` / ${l.variety.name}` : ""}`,
  }));

  return (
    <div>
      <PageHeader
        title="Cold Storage"
        breadcrumbs={
          <Breadcrumbs
            items={[
              { label: "Home", href: `/farms/${farmId}` },
              { label: "Processing", href: `/farms/${farmId}/processing` },
              { label: "Cold Storage" },
            ]}
          />
        }
      />

      {lotsQuery.isLoading && <LoadingSkeleton />}
      {lotsQuery.isError && <ErrorState error={lotsQuery.error} onRetry={() => lotsQuery.refetch()} />}
      {!lotsQuery.isLoading && !lotsQuery.isError && allLots.length === 0 && (
        <EmptyState
          title="No Finished Goods Lots yet"
          description="Pack a Graded Produce Lot first, then it can be placed into Cold Storage here."
        />
      )}

      {!lotsQuery.isLoading && !lotsQuery.isError && allLots.length > 0 && (
        <div className="flex flex-col gap-4">
          <label className="flex flex-col gap-1">
            <span className="text-sm font-medium text-ink">Finished Goods Lot</span>
            <FilterableSelect
              options={lotOptions}
              value={selectedLotId}
              onChange={(id) => {
                setSelectedLotId(id);
                setRecordSuccess(false);
                setRecordError(null);
              }}
              placeholder="Search by Lot code…"
              aria-label="Finished Goods Lot"
            />
          </label>

          {selectedLot && (
            <>
              {recordSuccess ? (
                <div className="flex flex-col gap-3 rounded-lg border border-border-subtle bg-surface p-4">
                  <h2 className="text-sm font-semibold text-ink">Movement recorded</h2>
                  <button
                    type="button"
                    onClick={() => setRecordSuccess(false)}
                    className="min-h-11 self-start rounded-md bg-brand-700 px-4 text-sm font-medium text-white hover:bg-brand-800"
                  >
                    Record another
                  </button>
                </div>
              ) : (
                <ColdStorageMovementForm
                  key={selectedLot.id}
                  farmId={farmId}
                  lot={selectedLot}
                  locations={locationsQuery.data ?? []}
                  isSubmitting={recordMutation.isPending}
                  serverError={recordError}
                  onSubmit={(payload) => {
                    setRecordError(null);
                    recordMutation.mutate(payload, {
                      onSuccess: () => setRecordSuccess(true),
                      onError: (error) => setRecordError(asAppError(error)),
                    });
                  }}
                />
              )}

              <div>
                <h3 className="mb-2 text-sm font-semibold text-ink">Movement history — {selectedLot.code}</h3>
                {movementsQuery.isLoading && <p className="text-sm text-ink-muted">Loading…</p>}
                {!movementsQuery.isLoading && (movementsQuery.data ?? []).length === 0 && (
                  <p className="text-sm text-ink-muted">No storage movements recorded yet for this Lot.</p>
                )}
                <ul className="flex flex-col gap-2">
                  {(movementsQuery.data ?? [])
                    .slice()
                    .sort((a, b) => b.effective_time.localeCompare(a.effective_time))
                    .map((m) => (
                      <li key={m.id} className="rounded-md border border-border-subtle p-3 text-sm">
                        <span className="font-medium capitalize text-ink">{m.movement_kind}</span>{" "}
                        <span className="text-ink-muted">
                          — {m.moved_weight_kg} kg / {m.moved_package_count} pkg —{" "}
                          {new Date(m.effective_time).toLocaleString()}
                        </span>
                      </li>
                    ))}
                </ul>
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}
