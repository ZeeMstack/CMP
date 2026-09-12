"use client";

import { useParams, useSearchParams } from "next/navigation";
import { useState } from "react";

import { LinkButton } from "@/components/admin/LinkButton";
import { Breadcrumbs } from "@/components/Breadcrumbs";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { FilterableSelect } from "@/components/FilterableSelect";
import { LoadingSkeleton } from "@/components/LoadingSkeleton";
import { PageHeader } from "@/components/PageHeader";
import { ColdStorageMovementForm } from "@/components/processing/ColdStorageMovementForm";
import { StatusBadge, type StatusTone } from "@/components/StatusBadge";
import { Button } from "@/components/ui/Button";
import { AppError } from "@/lib/errors/adapter";
import {
  useFinishedGoodsLots, useFinishedGoodsStorageMovements, useLocationsTree, useRecordFinishedGoodsStorageMovement,
} from "@/lib/query/hooks";

// Explicit labels for the three frozen movement kinds -- never invented,
// never a 4th kind. PLACE reads as the "settled" state (active/green),
// RELEASE as neutral (leaving Cold Storage entirely), TRANSFER as
// attention (still in Cold Storage, but moving between Locations).
const MOVEMENT_KIND_LABEL: Record<string, string> = { place: "Place", release: "Release", transfer: "Transfer" };
const MOVEMENT_KIND_TONE: Record<string, StatusTone> = { place: "active", release: "neutral", transfer: "attention" };

function asAppError(error: unknown): AppError {
  return error instanceof AppError ? error : new AppError("server_error", "Something went wrong. Please try again.");
}

/** PILOT-READY-001: the Cold Storage workspace -- pick a Finished Goods
 * Lot, then record a place/transfer/release movement for it, with that
 * Lot's own movement history shown alongside. Closes a confirmed pilot
 * blocker: the backend has always supported Cold Storage placement, but
 * it was previously only readable (never writable) from the frontend.
 *
 * PILOT-UX-002C: an optional `?finishedGoodsLotId=` deep link (the handoff
 * from a successful Packing) preselects that Lot -- resolved against this
 * page's own scoped `useFinishedGoodsLots` read, never trusted directly.
 * This only focuses the existing picker; it never places anything itself
 * (the operator still records the movement explicitly, exactly as before)
 * and this screen is otherwise unchanged. */
export default function ColdStoragePage() {
  const { farmId } = useParams<{ farmId: string }>();
  const searchParams = useSearchParams();
  const contextLotId = searchParams.get("finishedGoodsLotId");

  const [selectedLotId, setSelectedLotId] = useState("");
  const [contextResolved, setContextResolved] = useState(!contextLotId);
  const [contextInvalid, setContextInvalid] = useState(false);
  const [recordError, setRecordError] = useState<AppError | null>(null);
  const [recordSuccess, setRecordSuccess] = useState(false);

  const lotsQuery = useFinishedGoodsLots(farmId);
  const locationsQuery = useLocationsTree(farmId);
  const movementsQuery = useFinishedGoodsStorageMovements(farmId, selectedLotId || null);
  const recordMutation = useRecordFinishedGoodsStorageMovement(farmId);

  const allLots = lotsQuery.data ?? [];

  if (!contextResolved && !lotsQuery.isLoading && !lotsQuery.isError) {
    const match = allLots.find((l) => l.id === contextLotId);
    if (match) {
      setSelectedLotId(match.id);
    } else {
      setContextInvalid(true);
    }
    setContextResolved(true);
  }

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

      {contextInvalid && (
        <p role="alert" className="mb-4 rounded-md border border-wl-border-strong bg-wl-hold-bg p-3 text-sm text-wl-hold-fg">
          The requested Finished Goods Lot could not be found in this Farm. Select a Lot below.
        </p>
      )}

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
            <span className="text-sm font-medium text-wl-text">Finished Goods Lot</span>
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
              {/* PILOT-UX-003: a secondary, de-emphasized handoff -- movement
                  entry stays the primary action on this screen. Hands off
                  the actual, stable Finished Goods Lot id; Dispatch
                  re-resolves it through its own scoped, authorized read
                  (never trusts this link directly), mirroring the identical
                  `?finishedGoodsLotId=` pattern Packing already uses here. */}
              <div className="flex justify-end">
                <LinkButton
                  variant="secondary"
                  href={`/farms/${farmId}/processing/dispatch?finishedGoodsLotId=${selectedLot.id}`}
                >
                  Prepare dispatch
                </LinkButton>
              </div>
              {recordSuccess ? (
                <div className="flex flex-col gap-3 rounded-xl border border-wl-border bg-wl-surface-raised p-4">
                  <h2 className="font-serif text-base font-semibold text-wl-text">Movement recorded</h2>
                  <Button type="button" variant="primary" className="self-start" onClick={() => setRecordSuccess(false)}>
                    Record another
                  </Button>
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
                <h3 className="mb-2 font-serif text-sm font-semibold text-wl-text">Movement history — {selectedLot.code}</h3>
                {movementsQuery.isLoading && <p className="text-sm text-wl-text-secondary">Loading…</p>}
                {!movementsQuery.isLoading && (movementsQuery.data ?? []).length === 0 && (
                  <p className="text-sm text-wl-text-secondary">No storage movements recorded yet for this Lot.</p>
                )}
                <ul className="flex flex-col gap-2">
                  {(movementsQuery.data ?? [])
                    .slice()
                    .sort((a, b) => b.effective_time.localeCompare(a.effective_time))
                    .map((m) => (
                      <li
                        key={m.id}
                        className="flex flex-wrap items-center gap-2 rounded-xl border border-wl-border bg-wl-surface-raised p-3 text-sm"
                      >
                        <StatusBadge label={MOVEMENT_KIND_LABEL[m.movement_kind] ?? m.movement_kind} tone={MOVEMENT_KIND_TONE[m.movement_kind] ?? "neutral"} />
                        <span className="text-wl-text-secondary">
                          {m.moved_weight_kg} kg / {m.moved_package_count} pkg —{" "}
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
