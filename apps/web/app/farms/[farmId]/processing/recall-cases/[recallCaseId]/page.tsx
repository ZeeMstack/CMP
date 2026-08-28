"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";

import { Breadcrumbs } from "@/components/Breadcrumbs";
import { ErrorState } from "@/components/ErrorState";
import { LoadingSkeleton } from "@/components/LoadingSkeleton";
import { PageHeader } from "@/components/PageHeader";
import { CloseRecallCaseForm } from "@/components/processing/CloseRecallCaseForm";
import { TraceListSection } from "@/components/processing/TraceListSection";
import type { LocationTreeNode, RecallCaseDetailRead } from "@/lib/api/client";
import { AppError } from "@/lib/errors/adapter";
import {
  useCloseRecallCase, useCropBatch, useFinishedGoodsLot, useFinishedGoodsLots, useGradedProduceLot,
  useGradedProduceLots, useHarvestedProduceLots, useLocationsTree, useOperationalSummary, useRecallCase,
} from "@/lib/query/hooks";

function asAppError(error: unknown): AppError {
  return error instanceof AppError ? error : new AppError("server_error", "Something went wrong. Please try again.");
}

function fmtTime(iso: string) {
  return new Date(iso).toLocaleString();
}

/** Mirrors `traceability/page.tsx`'s own `flattenLocationLabels` -- a
 * separate local copy since this file belongs to Recall (Batch F), not the
 * Traceability route, even though both were built in the same batch. */
function flattenLocationLabels(nodes: LocationTreeNode[], pathPrefix: string[] = []): Map<string, string> {
  const map = new Map<string, string>();
  for (const node of nodes) {
    const path = [...pathPrefix, node.name];
    map.set(node.id, path.join(" / "));
    for (const [id, label] of flattenLocationLabels(node.children, path)) map.set(id, label);
  }
  return map;
}

/** Exactly one of `crop_batch_id`/`harvested_produce_lot_id`/
 * `graded_produce_lot_id`/`finished_goods_lot_id` is ever set on a Recall
 * Case (backend-enforced -- see `RecallCaseCreate`'s own scope fields).
 * Each branch below resolves that one id to its real code via the same
 * per-id read the entity's own detail screen already uses, and links to
 * that screen where a route exists (no detail route exists for a
 * Harvested Produce Lot, so it resolves a code but not a link). */
function CropBatchScopeSubject({ farmId, batchId }: { farmId: string; batchId: string }) {
  const q = useCropBatch(farmId, batchId);
  const label = q.data?.code ?? `${batchId.slice(0, 8)}…`;
  return (
    <ScopeSubjectRow
      kind="Crop Batch"
      label={label}
      resolved={Boolean(q.data)}
      href={`/farms/${farmId}/crop-batches/${batchId}`}
    />
  );
}

function HarvestedProduceLotScopeSubject({ farmId, produceLotId }: { farmId: string; produceLotId: string }) {
  // No single-Lot read exists for a Harvested Produce Lot -- resolved via
  // the same farm-wide list every Grading/Traceability screen already
  // fetches, matched client-side by id.
  const q = useHarvestedProduceLots(farmId);
  const lot = q.data?.find((l) => l.id === produceLotId);
  const label = lot?.code ?? `${produceLotId.slice(0, 8)}…`;
  return <ScopeSubjectRow kind="Harvested Produce Lot" label={label} resolved={Boolean(lot)} />;
}

function GradedProduceLotScopeSubject({ farmId, gplId }: { farmId: string; gplId: string }) {
  const q = useGradedProduceLot(farmId, gplId);
  const label = q.data?.code ?? `${gplId.slice(0, 8)}…`;
  return (
    <ScopeSubjectRow
      kind="Graded Produce Lot"
      label={label}
      resolved={Boolean(q.data)}
      href={`/farms/${farmId}/processing/graded-lots/${gplId}`}
    />
  );
}

function FinishedGoodsLotScopeSubject({ farmId, fgLotId }: { farmId: string; fgLotId: string }) {
  const q = useFinishedGoodsLot(farmId, fgLotId);
  const label = q.data?.code ?? `${fgLotId.slice(0, 8)}…`;
  return (
    <ScopeSubjectRow
      kind="Finished Goods Lot"
      label={label}
      resolved={Boolean(q.data)}
      href={`/farms/${farmId}/processing/finished-goods/${fgLotId}`}
    />
  );
}

function ScopeSubjectRow({ kind, label, resolved, href }: { kind: string; label: string; resolved: boolean; href?: string }) {
  return (
    <div>
      <dt className="text-xs font-medium uppercase tracking-wide text-ink-muted">Scope — {kind}</dt>
      <dd className={resolved ? "text-ink" : "font-mono text-ink-muted"}>
        {href ? (
          <Link href={href} className="font-medium hover:underline">
            {label}
          </Link>
        ) : (
          label
        )}
      </dd>
    </div>
  );
}

function ScopeSubject({ farmId, recallCase }: { farmId: string; recallCase: RecallCaseDetailRead }) {
  if (recallCase.crop_batch_id) return <CropBatchScopeSubject farmId={farmId} batchId={recallCase.crop_batch_id} />;
  if (recallCase.harvested_produce_lot_id) {
    return <HarvestedProduceLotScopeSubject farmId={farmId} produceLotId={recallCase.harvested_produce_lot_id} />;
  }
  if (recallCase.graded_produce_lot_id) return <GradedProduceLotScopeSubject farmId={farmId} gplId={recallCase.graded_produce_lot_id} />;
  if (recallCase.finished_goods_lot_id) return <FinishedGoodsLotScopeSubject farmId={farmId} fgLotId={recallCase.finished_goods_lot_id} />;
  return null;
}

/** `frozen_scope` only carries ids, not codes (`FrozenScopeRead`). Resolved
 * against the same farm-wide lists every other Processing/Traceability
 * screen already fetches (Batch/HPL/GPL/FGL), matched client-side by id --
 * no new endpoint, and an id genuinely absent from the current list (never
 * expected, since nothing here is ever hard-deleted) falls back to a
 * clearly-styled truncated id rather than a silent blank. */
function FrozenScopeSection({ farmId, recallCase }: { farmId: string; recallCase: RecallCaseDetailRead }) {
  const batchesQuery = useOperationalSummary(farmId, "all");
  const hplsQuery = useHarvestedProduceLots(farmId);
  const gplsQuery = useGradedProduceLots(farmId);
  const fglsQuery = useFinishedGoodsLots(farmId);

  function codeFor(id: string, list: { id: string; code: string }[] | undefined) {
    return list?.find((item) => item.id === id)?.code ?? null;
  }

  return (
    <div className="flex flex-col gap-4">
      <TraceListSection
        title="Crop Batches"
        items={recallCase.frozen_scope.crop_batch_ids}
        keyFor={(id) => id}
        emptyLabel="No Crop Batch was in scope."
        renderItem={(id) => {
          const code = codeFor(id, batchesQuery.data);
          return (
            <Link href={`/farms/${farmId}/crop-batches/${id}`} className={code ? "font-medium text-ink hover:underline" : "font-mono text-ink-muted hover:underline"}>
              {code ?? `${id.slice(0, 8)}…`}
            </Link>
          );
        }}
      />
      <TraceListSection
        title="Harvested Produce Lots"
        items={recallCase.frozen_scope.harvested_produce_lot_ids}
        keyFor={(id) => id}
        emptyLabel="No Harvested Produce Lot was in scope."
        renderItem={(id) => {
          const code = codeFor(id, hplsQuery.data);
          return <span className={code ? "text-ink" : "font-mono text-ink-muted"}>{code ?? `${id.slice(0, 8)}…`}</span>;
        }}
      />
      <TraceListSection
        title="Graded Produce Lots"
        items={recallCase.frozen_scope.graded_produce_lot_ids}
        keyFor={(id) => id}
        emptyLabel="No Graded Produce Lot was in scope."
        renderItem={(id) => {
          const code = codeFor(id, gplsQuery.data);
          return (
            <Link href={`/farms/${farmId}/processing/graded-lots/${id}`} className={code ? "font-medium text-ink hover:underline" : "font-mono text-ink-muted hover:underline"}>
              {code ?? `${id.slice(0, 8)}…`}
            </Link>
          );
        }}
      />
      <TraceListSection
        title="Finished Goods Lots"
        items={recallCase.frozen_scope.finished_goods_lot_ids}
        keyFor={(id) => id}
        emptyLabel="No Finished Goods Lot was in scope."
        renderItem={(id) => {
          const code = codeFor(id, fglsQuery.data);
          return (
            <Link href={`/farms/${farmId}/processing/finished-goods/${id}`} className={code ? "font-medium text-ink hover:underline" : "font-mono text-ink-muted hover:underline"}>
              {code ?? `${id.slice(0, 8)}…`}
            </Link>
          );
        }}
      />
    </div>
  );
}

/** POSTHARVEST-OPS-001G: Recall Case detail -- identity/status, the one
 * scope this case was opened against, what was contained at the moment it
 * opened (`frozen_scope`) and what is currently affected right now
 * (`live_state`), plus a Close action while still open. Every section is
 * real structured fields, never `JSON.stringify` -- see UI-OPT-001. */
export default function RecallCaseDetailPage() {
  const { farmId, recallCaseId } = useParams<{ farmId: string; recallCaseId: string }>();
  const { data: recallCase, isLoading, error, refetch } = useRecallCase(farmId, recallCaseId);
  const closeMutation = useCloseRecallCase(farmId);
  const [closeError, setCloseError] = useState<AppError | null>(null);

  const locationsQuery = useLocationsTree(farmId);
  const locationLabelById = locationsQuery.data ? flattenLocationLabels(locationsQuery.data) : new Map<string, string>();

  if (isLoading) return <LoadingSkeleton rows={4} label="Loading Recall Case" />;
  if (error) return <ErrorState error={error} onRetry={() => refetch()} />;
  if (!recallCase) return null;

  return (
    <div>
      <PageHeader
        title={recallCase.code}
        breadcrumbs={
          <Breadcrumbs
            items={[
              { label: "Home", href: `/farms/${farmId}` },
              { label: "Processing", href: `/farms/${farmId}/processing` },
              { label: "Recall Cases", href: `/farms/${farmId}/processing/recall-cases` },
              { label: recallCase.code },
            ]}
          />
        }
      />

      <div className="flex flex-col gap-4">
        <dl className="grid grid-cols-2 gap-x-4 gap-y-3 rounded-xl border border-border-subtle bg-surface p-4 text-sm sm:grid-cols-3">
          <div>
            <dt className="text-xs font-medium uppercase tracking-wide text-ink-muted">Status</dt>
            <dd>
              <span
                className={`inline-flex w-fit items-center rounded-full px-2 py-0.5 text-xs font-medium ${
                  recallCase.is_open ? "bg-red-100 text-red-800" : "bg-surface-subtle text-ink-muted"
                }`}
              >
                {recallCase.is_open ? "Open" : "Closed"}
              </span>
            </dd>
          </div>
          <ScopeSubject farmId={farmId} recallCase={recallCase} />
          <div>
            <dt className="text-xs font-medium uppercase tracking-wide text-ink-muted">Reason</dt>
            <dd className="text-ink">{recallCase.reason_code} — {recallCase.reason_text}</dd>
          </div>
          <div>
            <dt className="text-xs font-medium uppercase tracking-wide text-ink-muted">Opened</dt>
            <dd className="text-ink">{fmtTime(recallCase.effective_time)}</dd>
          </div>
          {recallCase.closure && (
            <div>
              <dt className="text-xs font-medium uppercase tracking-wide text-ink-muted">Closed at</dt>
              <dd className="text-ink">
                {fmtTime(recallCase.closure.effective_time)} — {recallCase.closure.close_reason}
              </dd>
            </div>
          )}
        </dl>

        <div>
          <h2 className="mb-2 font-serif text-sm font-semibold text-ink">Contained at time of opening</h2>
          <p className="mb-2 text-xs text-ink-muted">
            Frozen the moment this case was opened -- never updated afterward, even if more Lots are later derived
            from the same source.
          </p>
          <FrozenScopeSection farmId={farmId} recallCase={recallCase} />
        </div>

        <div>
          <h2 className="mb-2 font-serif text-sm font-semibold text-ink">Currently affected</h2>
          <p className="mb-2 text-xs text-ink-muted">Live, as of this page load -- reflects Dispatch/Cold Storage activity since the case opened.</p>
          <div className="flex flex-col gap-4">
            <TraceListSection
              title="Finished Goods Lots"
              items={recallCase.live_state.finished_goods_lots}
              keyFor={(l) => l.finished_goods_lot_id}
              emptyLabel="No Finished Goods Lots currently affected."
              renderItem={(l) => (
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <Link href={`/farms/${farmId}/processing/finished-goods/${l.finished_goods_lot_id}`} className="font-medium text-ink hover:underline">
                    {l.code}
                  </Link>
                  <span className="text-ink-muted">
                    available {l.available_weight_kg} kg — placed {l.placed_weight_kg} kg — unplaced {l.unplaced_weight_kg} kg
                  </span>
                </div>
              )}
            />
            <TraceListSection
              title="Cold storage"
              items={recallCase.live_state.storage}
              keyFor={(s) => `${s.finished_goods_lot_id}-${s.location_id}`}
              emptyLabel="Nothing currently placed in Cold Storage."
              renderItem={(s) => {
                const label = locationLabelById.get(s.location_id);
                return (
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className={label ? "text-ink" : "font-mono text-ink-muted"}>{label ?? `${s.location_id.slice(0, 8)}…`}</span>
                    <span className="text-ink-muted">{s.weight_kg} kg / {s.package_count} pkg</span>
                  </div>
                );
              }}
            />
            <TraceListSection
              title="Dispatches"
              items={recallCase.live_state.dispatches}
              keyFor={(d) => d.dispatch_line_id}
              emptyLabel="Nothing has been dispatched."
              renderItem={(d) => (
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="font-medium text-ink">{d.dispatch_event_code}</span>
                  <span className="text-ink-muted">{d.dispatched_weight_kg} kg / {d.dispatched_package_count} pkg — {fmtTime(d.effective_time)}</span>
                </div>
              )}
            />
          </div>
        </div>

        {recallCase.is_open && (
          <CloseRecallCaseForm
            isSubmitting={closeMutation.isPending}
            serverError={closeError}
            onSubmit={(payload) => {
              setCloseError(null);
              closeMutation.mutate(
                { recallCaseId, payload },
                { onError: (err) => setCloseError(asAppError(err)) },
              );
            }}
          />
        )}
      </div>
    </div>
  );
}
