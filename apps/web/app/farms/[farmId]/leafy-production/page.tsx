"use client";

import { useParams } from "next/navigation";
import { useState } from "react";

import { Breadcrumbs } from "@/components/Breadcrumbs";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { LoadingSkeleton } from "@/components/LoadingSkeleton";
import { PageHeader } from "@/components/PageHeader";
import { PlantLossHistoryPanel } from "@/components/leafy/PlantLossHistoryPanel";
import { RecordPlantLossForm } from "@/components/leafy/RecordPlantLossForm";
import { Button } from "@/components/ui/Button";
import { Tabs } from "@/components/ui/Tabs";
import type { ActiveProductionPlateRead, CorrectProductionDispositionCreate } from "@/lib/api/client";
import { AppError } from "@/lib/errors/adapter";
import {
  useActiveProductionPlates,
  useCorrectProductionDisposition,
  useProductionDispositionHistory,
  useRecordProductionDisposition,
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

  const activePlatesQuery = useActiveProductionPlates(farmId);
  const historyQuery = useProductionDispositionHistory(farmId);
  const recordMutation = useRecordProductionDisposition(farmId);
  const correctMutation = useCorrectProductionDisposition(farmId);

  // Derived, never a frozen snapshot: a 409 on record invalidates the
  // Active Production Plates query, and this stays in sync with the
  // refetched authoritative population automatically -- the Record form
  // below always sees the current `current_living_population`, satisfying
  // the "refresh population" half of the 409 contract (the "force
  // re-review" half is the form's own back-to-Configure reset).
  const selectedPlate: ActiveProductionPlateRead | null =
    (activePlatesQuery.data ?? []).find((p) => p.batch_carrier_assignment_id === selectedPlateId) ?? null;

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
          ) : (
            <>
              {activePlatesQuery.isLoading && <LoadingSkeleton rows={4} label="Loading active Production Plates" />}
              {activePlatesQuery.isError && (
                <ErrorState error={activePlatesQuery.error} onRetry={() => activePlatesQuery.refetch()} />
              )}
              {activePlatesQuery.isSuccess && (activePlatesQuery.data ?? []).length === 0 && (
                <EmptyState
                  title="No active Production Plates in this Farm."
                  description="Plates appear here once a Production Transfer has placed living plants in Leafy Production."
                />
              )}
              {activePlatesQuery.isSuccess && (activePlatesQuery.data ?? []).length > 0 && (
                <ul className="flex flex-col gap-3">
                  {(activePlatesQuery.data ?? []).map((plate) => (
                    <li
                      key={plate.batch_carrier_assignment_id}
                      className="flex flex-col gap-2 rounded-xl border border-border-subtle bg-surface p-3 sm:flex-row sm:items-center sm:justify-between"
                    >
                      <div className="flex flex-col gap-1">
                        <span className="font-serif text-sm font-semibold text-ink">
                          {plate.plate_code} — {plate.batch_code}
                        </span>
                        <span className="text-xs text-ink-muted">
                          {plate.crop_common_name}
                          {plate.variety_name ? ` / ${plate.variety_name}` : ""} · Living{" "}
                          {plate.current_living_population.toLocaleString()}
                        </span>
                        {plate.current_location ? (
                          <span className="text-xs text-ink-muted">{plate.current_location.ancestry_label}</span>
                        ) : (
                          <span className="text-xs text-red-700">No current Leafy location on record</span>
                        )}
                      </div>
                      <Button
                        type="button"
                        variant="primary"
                        className="self-start sm:self-center"
                        onClick={() => setSelectedPlateId(plate.batch_carrier_assignment_id)}
                      >
                        Record Plant Loss
                      </Button>
                    </li>
                  ))}
                </ul>
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
