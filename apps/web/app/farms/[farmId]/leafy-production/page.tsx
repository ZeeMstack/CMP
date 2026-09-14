"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";

import { Breadcrumbs } from "@/components/Breadcrumbs";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { LoadingSkeleton } from "@/components/LoadingSkeleton";
import { PageHeader } from "@/components/PageHeader";
import { MoveProductionPlateForm } from "@/components/leafy/MoveProductionPlateForm";
import { PlantLossHistoryPanel } from "@/components/leafy/PlantLossHistoryPanel";
import { RecordPlantLossForm } from "@/components/leafy/RecordPlantLossForm";
import { Button } from "@/components/ui/Button";
import { Tabs } from "@/components/ui/Tabs";
import type { ActiveProductionPlateRead, CorrectProductionDispositionCreate, MovementCreate } from "@/lib/api/client";
import { AppError } from "@/lib/errors/adapter";
import {
  useActiveProductionPlates,
  useCorrectProductionDisposition,
  useProductionDispositionHistory,
  useRecordProductionDisposition,
  useRelocateLeafyProductionPlate,
} from "@/lib/query/hooks";

const TABS = [
  { id: "active", label: "Active Production Plates" },
  { id: "history", label: "Plant Loss History" },
] as const;

function asAppError(error: unknown): AppError {
  return error instanceof AppError ? error : new AppError("server_error", "Something went wrong. Please try again.");
}

/** LEAFY-OPS-001: the first actual Leafy Production operations workspace --
 * two sections, "Active Production Plates" (Record Plant Loss) and "Plant
 * Loss History" (correction), prioritizing greenhouse-floor operation over
 * analytics (section 40, frozen). Does not rename/remove the existing
 * Production Transfer workflow (005B), which remains its own nav entry. */
export default function LeafyProductionPage() {
  const { farmId } = useParams<{ farmId: string }>();
  const [tab, setTab] = useState<"active" | "history">("active");
  const [selectedPlateId, setSelectedPlateId] = useState<string | null>(null);
  const [recordError, setRecordError] = useState<AppError | null>(null);
  const [recordSuccess, setRecordSuccess] = useState<{ plateCode: string; resulting: number; released: boolean } | null>(null);
  const [correctingEventId, setCorrectingEventId] = useState<string | null>(null);
  const [correctError, setCorrectError] = useState<AppError | null>(null);
  const [movingPlateId, setMovingPlateId] = useState<string | null>(null);
  const [moveError, setMoveError] = useState<AppError | null>(null);
  const [moveSuccess, setMoveSuccess] = useState<{ plateCode: string; toLabel: string } | null>(null);
  const [batchFilter, setBatchFilter] = useState("");
  const [locationFilter, setLocationFilter] = useState("");

  const activePlatesQuery = useActiveProductionPlates(farmId);
  const historyQuery = useProductionDispositionHistory(farmId);
  const recordMutation = useRecordProductionDisposition(farmId);
  const correctMutation = useCorrectProductionDisposition(farmId);
  const relocateMutation = useRelocateLeafyProductionPlate(farmId);

  // Derived, never a frozen snapshot: a 409 on record invalidates the
  // Active Production Plates query, and this stays in sync with the
  // refetched authoritative population automatically -- the Record form
  // below always sees the current `current_living_population`, satisfying
  // the "refresh population" half of the 409 contract (the "force
  // re-review" half is the form's own back-to-Configure reset).
  const selectedPlate: ActiveProductionPlateRead | null =
    (activePlatesQuery.data ?? []).find((p) => p.batch_carrier_assignment_id === selectedPlateId) ?? null;
  const movingPlate: ActiveProductionPlateRead | null =
    (activePlatesQuery.data ?? []).find((p) => p.batch_carrier_assignment_id === movingPlateId) ?? null;

  // Filtering is entirely client-side over the existing farm-scoped read --
  // no new endpoint/field, just narrowing what's already loaded. Batch
  // options are the distinct Batches actually present, never a separate
  // Batch-listing read.
  const allActivePlates = activePlatesQuery.data ?? [];
  const batchOptions = Array.from(
    new Map(allActivePlates.map((p) => [p.batch_id, p.batch_code])).entries(),
  ).sort((a, b) => a[1].localeCompare(b[1]));
  const visiblePlates = allActivePlates.filter((p) => {
    if (batchFilter && p.batch_id !== batchFilter) return false;
    if (locationFilter && !(p.current_location?.ancestry_label ?? "").toLowerCase().includes(locationFilter.toLowerCase())) {
      return false;
    }
    return true;
  });

  return (
    <div>
      <PageHeader
        title="Leafy Production"
        breadcrumbs={
          <Breadcrumbs
            items={[
              { label: "Home", href: `/farms/${farmId}` },
              { label: "Production Operations" },
              { label: "Leafy Production" },
            ]}
          />
        }
      />

      <div className="mb-6">
        <Tabs
          tabs={TABS.map(({ id, label }) => ({ id, label }))}
          activeId={tab}
          onChange={(id) => setTab(id as "active" | "history")}
          aria-label="Leafy Production sections"
        />
      </div>

      {tab === "active" && (
        <div className="flex flex-col gap-4">
          {recordSuccess ? (
            // Gated on `recordSuccess` itself, never on `selectedPlate` --
            // a zero-exhausting record removes the Plate from this list on
            // refetch (it's now released), which must never hide the
            // success screen for the operator who just recorded it.
            <div className="flex flex-col gap-3 rounded-xl border border-border-subtle bg-surface p-4">
              <h2 className="font-serif text-base font-semibold text-ink">Plant loss recorded</h2>
              <dl className="text-sm">
                <div>
                  <dt className="text-ink-muted">Plate</dt>
                  <dd className="font-medium text-ink">{recordSuccess.plateCode}</dd>
                </div>
                <div>
                  <dt className="text-ink-muted">Current Living</dt>
                  <dd className="text-base font-semibold text-ink">{recordSuccess.resulting.toLocaleString()}</dd>
                </div>
              </dl>
              {recordSuccess.released && (
                <p className="text-sm text-ink-muted">
                  Current Living: 0. Biological assignment released. The physical Plate remains at its current
                  location — it has not been moved, sanitized, or marked available.
                </p>
              )}
              <Button
                type="button"
                variant="primary"
                className="self-start"
                onClick={() => {
                  setSelectedPlateId(null);
                  setRecordSuccess(null);
                  setRecordError(null);
                }}
              >
                Done
              </Button>
            </div>
          ) : moveSuccess ? (
            <div className="flex flex-col gap-3 rounded-xl border border-border-subtle bg-surface p-4">
              <h2 className="font-serif text-base font-semibold text-ink">Plate moved</h2>
              <dl className="text-sm">
                <div>
                  <dt className="text-ink-muted">Plate</dt>
                  <dd className="font-medium text-ink">{moveSuccess.plateCode}</dd>
                </div>
                <div>
                  <dt className="text-ink-muted">New location</dt>
                  <dd className="font-medium text-ink">{moveSuccess.toLabel}</dd>
                </div>
              </dl>
              <Button
                type="button"
                variant="primary"
                className="self-start"
                onClick={() => {
                  setMovingPlateId(null);
                  setMoveSuccess(null);
                  setMoveError(null);
                }}
              >
                Done
              </Button>
            </div>
          ) : selectedPlate ? (
            <RecordPlantLossForm
              plateCode={selectedPlate.plate_code}
              batchCarrierAssignmentId={selectedPlate.batch_carrier_assignment_id}
              currentLivingPopulation={selectedPlate.current_living_population}
              isSubmitting={recordMutation.isPending}
              serverError={recordError}
              onCancel={() => {
                setSelectedPlateId(null);
                setRecordError(null);
              }}
              onSubmit={(payload) => {
                setRecordError(null);
                recordMutation.mutate(payload, {
                  onSuccess: (result) => {
                    setRecordSuccess({
                      plateCode: selectedPlate.plate_code,
                      resulting: result.resulting_living_population,
                      released: result.assignment_released,
                    });
                  },
                  onError: (error) => setRecordError(asAppError(error)),
                });
              }}
            />
          ) : selectedPlateId ? (
            // The selected Plate is no longer active (its lineage was
            // fully exhausted by another concurrent disposition before this
            // form could load/refresh) -- never a blank/frozen form.
            <div className="flex flex-col gap-3 rounded-xl border border-border-subtle bg-surface p-4">
              <p className="text-sm text-ink-muted">
                This Plate is no longer active — its living population may have already reached zero elsewhere.
              </p>
              <Button type="button" variant="secondary" className="self-start" onClick={() => setSelectedPlateId(null)}>
                Back to Active Production Plates
              </Button>
            </div>
          ) : movingPlate ? (
            <MoveProductionPlateForm
              farmId={farmId}
              plate={movingPlate}
              isSubmitting={relocateMutation.isPending}
              serverError={moveError}
              onCancel={() => {
                setMovingPlateId(null);
                setMoveError(null);
              }}
              onSubmit={(payload: MovementCreate, toLabel: string) => {
                setMoveError(null);
                relocateMutation.mutate(payload, {
                  onSuccess: () => {
                    setMoveSuccess({ plateCode: movingPlate.plate_code, toLabel });
                  },
                  onError: (error) => setMoveError(asAppError(error)),
                });
              }}
            />
          ) : movingPlateId ? (
            // The Plate being moved is no longer active (e.g. its living
            // population reached zero elsewhere before this form loaded) --
            // never a blank/frozen form.
            <div className="flex flex-col gap-3 rounded-xl border border-border-subtle bg-surface p-4">
              <p className="text-sm text-ink-muted">
                This Plate is no longer active — it may have already been moved or released elsewhere.
              </p>
              <Button type="button" variant="secondary" className="self-start" onClick={() => setMovingPlateId(null)}>
                Back to Active Production Plates
              </Button>
            </div>
          ) : (
            <>
              {activePlatesQuery.isLoading && <LoadingSkeleton rows={4} label="Loading active Production Plates" />}
              {activePlatesQuery.isError && (
                <ErrorState error={activePlatesQuery.error} onRetry={() => activePlatesQuery.refetch()} />
              )}
              {activePlatesQuery.isSuccess && allActivePlates.length === 0 && (
                <EmptyState
                  title="No active Production Plates in this Farm."
                  description="Plates appear here once a Production Transfer has placed living plants in Leafy Production."
                />
              )}
              {activePlatesQuery.isSuccess && allActivePlates.length > 0 && (
                <>
                  <div className="flex flex-wrap items-end gap-3">
                    <label className="flex flex-col gap-1">
                      <span className="text-xs font-medium text-ink-muted">Batch</span>
                      <select
                        className="min-h-9 rounded-md border border-border-subtle bg-surface px-2.5 text-sm text-ink"
                        value={batchFilter}
                        onChange={(e) => setBatchFilter(e.target.value)}
                      >
                        <option value="">All batches</option>
                        {batchOptions.map(([id, code]) => (
                          <option key={id} value={id}>{code}</option>
                        ))}
                      </select>
                    </label>
                    <label className="flex flex-col gap-1">
                      <span className="text-xs font-medium text-ink-muted">Location</span>
                      <input
                        type="text"
                        className="min-h-9 rounded-md border border-border-subtle bg-surface px-2.5 text-sm text-ink"
                        placeholder="Search greenhouse/zone/table…"
                        value={locationFilter}
                        onChange={(e) => setLocationFilter(e.target.value)}
                      />
                    </label>
                  </div>

                  {visiblePlates.length === 0 ? (
                    <p className="text-sm text-ink-muted">No Production Plates match this filter.</p>
                  ) : (
                    <div className="overflow-x-auto rounded-xl border border-border-subtle bg-surface">
                      <table className="w-full min-w-[760px] text-left text-sm">
                        <thead>
                          <tr className="border-b border-border-subtle text-ink-muted">
                            <th className="p-3 font-medium">Plate</th>
                            <th className="p-3 font-medium">Batch / Variety</th>
                            <th className="p-3 font-medium">Living</th>
                            <th className="p-3 font-medium">Location</th>
                            <th className="p-3 font-medium" />
                          </tr>
                        </thead>
                        <tbody>
                          {visiblePlates.map((plate) => (
                            <tr key={plate.batch_carrier_assignment_id} className="border-b border-border-subtle last:border-0">
                              <td className="p-3 font-medium text-ink">{plate.plate_code}</td>
                              <td className="p-3 text-ink">
                                {plate.batch_code}
                                <span className="block text-xs text-ink-muted">
                                  {plate.crop_common_name}
                                  {plate.variety_name ? ` / ${plate.variety_name}` : ""}
                                </span>
                              </td>
                              <td className="p-3 tabular-nums text-ink">{plate.current_living_population.toLocaleString()}</td>
                              <td className="p-3 text-ink">
                                {plate.current_location ? (
                                  <span className="text-xs text-ink-muted">{plate.current_location.ancestry_label}</span>
                                ) : (
                                  <span className="text-xs text-red-700">No current Leafy location on record</span>
                                )}
                              </td>
                              <td className="p-3">
                                <div className="flex flex-wrap gap-2">
                                  <Button
                                    type="button"
                                    variant="secondary"
                                    disabled={!plate.current_location}
                                    onClick={() => setMovingPlateId(plate.batch_carrier_assignment_id)}
                                  >
                                    Move plate
                                  </Button>
                                  <Button
                                    type="button"
                                    variant="primary"
                                    onClick={() => setSelectedPlateId(plate.batch_carrier_assignment_id)}
                                  >
                                    Record Plant Loss
                                  </Button>
                                  <Link
                                    href={`/farms/${farmId}/observations?batchId=${plate.batch_id}&assignmentId=${plate.batch_carrier_assignment_id}`}
                                    className="inline-flex h-9 items-center justify-center rounded-lg border border-wl-border-strong bg-wl-surface-raised px-4 text-sm font-medium text-wl-text hover:bg-wl-surface-hover"
                                  >
                                    Record observation
                                  </Link>
                                </div>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </>
              )}
            </>
          )}
        </div>
      )}

      {tab === "history" && (
        <PlantLossHistoryPanel
          lineages={historyQuery.data ?? []}
          // Backend enforces BIOLOGICAL_DISPOSITION_CORRECT authoritatively;
          // the frontend has no role-awareness context yet to gate this
          // visually beyond that -- an unauthorized attempt surfaces the
          // backend's own 403 as a normal error, consistent with every
          // other command in this app.
          canCorrect={true}
          correctingEventId={correctingEventId}
          isSubmitting={correctMutation.isPending}
          serverError={correctError}
          onCorrect={async (eventId: string, payload: CorrectProductionDispositionCreate) => {
            setCorrectingEventId(eventId);
            setCorrectError(null);
            try {
              await correctMutation.mutateAsync({ eventId, payload });
            } catch (error) {
              setCorrectError(asAppError(error));
              throw error;
            } finally {
              setCorrectingEventId(null);
            }
          }}
        />
      )}
    </div>
  );
}
