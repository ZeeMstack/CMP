"use client";

import { useParams } from "next/navigation";
import { useState } from "react";

import { Breadcrumbs } from "@/components/Breadcrumbs";
import { PageHeader } from "@/components/PageHeader";
import { StoreSubNav } from "@/components/store-inventory/StoreSubNav";
import { Button } from "@/components/ui/Button";
import type { InventoryStorageTransferCreate } from "@/lib/api/client";
import { useFrozenSubmission, type UseFrozenSubmissionResult } from "@/lib/commands/frozenSubmission";
import { nowLocalDateTime } from "@/lib/datetime";
import { AppError } from "@/lib/errors/adapter";
import { activeBinsWithPaths } from "@/lib/locations/bins";
import {
  useCohortStorageBreakdown, useFarms, useInventoryItems, useItemExistenceProvenance, useItemFarmAvailability,
  useItemsExistenceSummary, useItemStorageBreakdown, useLocationsTree, useQualityWorkQueue,
  useRecordInventoryScrap, useRecordInventoryStorageTransfer, useUoms,
} from "@/lib/query/hooks";

// PILOT-BLOCKER-009 R7: the Quality work queue lists every positive-balance
// cohort company-wide, RELEASED/HOLD_RELEASED (ordinary, usable) stock
// included (docs/domain/STORE_INVENTORY_MODEL.md §11) -- membership alone is
// never an exception. Only these `current_state` values are an authoritative
// exception a cohort can be in.
const EXCEPTION_STATES = new Set(["RECEIVED_QUARANTINED", "HELD", "REJECTED"]);
const EXCEPTION_REASON_LABEL: Record<string, string> = {
  RECEIVED_QUARANTINED: "Awaiting Quality",
  HELD: "On hold",
  REJECTED: "Rejected",
};

const inputClass =
  "min-h-9 w-full rounded-md border border-wl-border bg-wl-surface px-2 text-xs text-wl-text focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-wl-focus";
const labelClass = "block text-[11px] font-medium text-wl-text-secondary";

function asAppError(error: unknown): AppError {
  return error instanceof AppError ? error : new AppError("server_error", "Something went wrong. Please try again.");
}

/** STORE-INV-002B: compact "Move stock" -- From Bin / To Bin / Quantity,
 * scoped to one cohort (a transfer moves one cohort's own custody between
 * two Bins in the same Farm; never a giant form, no UUIDs shown).
 *
 * PILOT-BLOCKER-010 R3: `command` and `transferMutation` are now owned by
 * the page (`StoreInventoryInventoryPage`), not this form instance --
 * passed down as props rather than created here with their own
 * `useFrozenSubmission`/`useRecordInventoryStorageTransfer` calls. This form
 * is disposable (Hide detail, switching the selected Item, or a query
 * refresh can all unmount it at any time); the frozen `client_command_id`/
 * payload/outcome must not live inside something that disposable -- see the
 * page-level `MoveRecoveryBanner` below, which is what actually keeps an
 * unresolved command's Retry reachable once this form is gone. */
function MoveStockForm({
  cohortId, farmId, fromBins, toBins, onDone, command, transferMutation,
}: {
  cohortId: string;
  farmId: string;
  fromBins: { id: string; label: string; balance: string }[];
  toBins: { id: string; label: string }[];
  onDone: () => void;
  command: UseFrozenSubmissionResult<InventoryStorageTransferCreate>;
  transferMutation: ReturnType<typeof useRecordInventoryStorageTransfer>;
}) {
  const [sourceId, setSourceId] = useState(fromBins[0]?.id ?? "");
  const [destId, setDestId] = useState(toBins.find((b) => b.id !== fromBins[0]?.id)?.id ?? toBins[0]?.id ?? "");
  const [quantity, setQuantity] = useState("");
  const [effectiveTime, setEffectiveTime] = useState(() => nowLocalDateTime());

  // PILOT-BLOCKER-008 A5: identical fix to Putaway's (A3) -- while
  // uncertain, every control that could alter the payload is disabled and
  // the displayed values come from the frozen submitted payload, never
  // live form state.
  const isUncertain = command.outcome === "uncertain";
  const isSubmitting = command.outcome === "submitting";
  const fieldsDisabled = isSubmitting || isUncertain;
  const frozen = command.frozenPayload;
  const frozenSourceLabel = frozen ? fromBins.find((b) => b.id === frozen.source_location_id)?.label ?? frozen.source_location_id : null;
  const frozenDestLabel = frozen ? toBins.find((b) => b.id === frozen.destination_location_id)?.label ?? frozen.destination_location_id : null;

  function handleSettled(payload: InventoryStorageTransferCreate) {
    transferMutation.mutate(
      { farmId, payload },
      {
        onSuccess: () => {
          command.handleSuccess();
          setQuantity("");
          onDone();
        },
        onError: (err) => command.handleError(asAppError(err)),
      },
    );
  }

  // PILOT-BLOCKER-010 R3: once uncertain, this row no longer offers its own
  // Retry -- the page-level `MoveRecoveryBanner` (always visible, survives
  // this very form unmounting) is the ONE canonical place to retry, so there
  // is never a moment with two different Retry buttons for the same
  // command. This row just points there, using the exact same frozen
  // values it would have shown inline before, computed here only for this
  // short pointer (not for a second interactive recovery block).
  if (isUncertain && frozen) {
    return (
      <div className="flex flex-col gap-1 rounded-lg border border-amber-300 bg-amber-50 p-3 text-xs text-amber-900">
        <p className="font-medium">Result unknown for this Move.</p>
        <p>
          {frozenSourceLabel} → {frozenDestLabel}, quantity {frozen.quantity}. See the recovery notice at the top of
          the page to retry -- do not repeat this operation as a new transaction.
        </p>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-2 rounded-lg border border-wl-border bg-wl-surface p-3">
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
        <label className="flex flex-col gap-1">
          <span className={labelClass}>From Bin</span>
          <select
            className={inputClass} value={sourceId} onChange={(e) => setSourceId(e.target.value)}
            disabled={fieldsDisabled}
          >
            {fromBins.map((b) => (
              <option key={b.id} value={b.id}>{b.label} ({b.balance})</option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1">
          <span className={labelClass}>To Bin</span>
          <select
            className={inputClass} value={destId} onChange={(e) => setDestId(e.target.value)}
            disabled={fieldsDisabled}
          >
            {toBins.map((b) => (
              <option key={b.id} value={b.id}>{b.label}</option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1">
          <span className={labelClass}>Quantity</span>
          <input
            className={inputClass}
            type="number"
            min="0"
            step="any"
            value={quantity}
            onChange={(e) => setQuantity(e.target.value)}
            disabled={fieldsDisabled}
          />
        </label>
      </div>
      <label className="flex flex-col gap-1">
        <span className={labelClass}>Effective time</span>
        <input
          className={inputClass}
          type="datetime-local"
          value={effectiveTime}
          onChange={(e) => setEffectiveTime(e.target.value)}
          disabled={fieldsDisabled}
        />
      </label>

      {command.error && (
        <p className="rounded-md border border-wl-border bg-wl-flag-bg p-2 text-xs text-wl-flag-fg">
          {command.error.message}
        </p>
      )}

      <div className="flex gap-2">
        <Button
          type="button"
          variant="primary"
          disabled={
            fieldsDisabled || !sourceId || !destId || sourceId === destId ||
            !quantity || Number(quantity) <= 0
          }
          onClick={() => {
            const payload = command.submit((clientCommandId) => ({
              client_command_id: clientCommandId,
              inventory_quantity_cohort_id: cohortId,
              source_location_id: sourceId,
              destination_location_id: destId,
              quantity,
              effective_time: new Date(effectiveTime).toISOString(),
              note: null,
            }));
            handleSettled(payload);
          }}
        >
          {isSubmitting ? "Submitting…" : "Confirm move"}
        </Button>
        <Button type="button" variant="secondary" onClick={onDone} disabled={fieldsDisabled}>
          Cancel
        </Button>
      </div>
    </div>
  );
}

/** PILOT-BLOCKER-010 R3: the stable, page-level recovery surface for a Move
 * whose result is unknown -- rendered regardless of which Item is currently
 * selected, whether the detail panel is open, or whether the
 * `CohortCustodyRow`/`MoveStockForm` instance that originally submitted it
 * is even mounted right now. Always visible near the top of the page (never
 * scoped inside the disposable detail panel) for exactly as long as
 * `moveCommand.outcome !== "editing"`. Bin labels are looked up against
 * `activeBins` (the page's own Farm-wide, always-fetched active Bin list),
 * never against the per-cohort `fromBins` list that only exists while the
 * originating row happens to be mounted -- that per-cohort list is what
 * would have disappeared with the row. */
function MoveRecoveryBanner({
  frozenPayload, activeBins, onRetry,
}: {
  frozenPayload: InventoryStorageTransferCreate;
  activeBins: { id: string; label: string }[];
  onRetry: () => void;
}) {
  const sourceLabel = activeBins.find((b) => b.id === frozenPayload.source_location_id)?.label ?? frozenPayload.source_location_id;
  const destLabel = activeBins.find((b) => b.id === frozenPayload.destination_location_id)?.label ?? frozenPayload.destination_location_id;
  return (
    <div
      role="alert"
      className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-amber-300 bg-amber-50 p-3 text-xs text-amber-900"
    >
      <div>
        <p className="font-semibold">Result unknown -- we couldn&apos;t confirm whether this Move was recorded.</p>
        <p>
          {sourceLabel} → {destLabel}, quantity {frozenPayload.quantity}. Do not repeat this operation as a new
          transaction.
        </p>
      </div>
      {/* This banner only ever renders while `outcome === "uncertain"` (never
          while a retry is actually in flight, since that flips the outcome
          to "submitting" and this banner away) -- so Retry here is never
          itself in a disabled/pending state to represent. */}
      <Button type="button" variant="primary" onClick={onRetry}>
        Retry
      </Button>
    </div>
  );
}

/** STORE-INV-004: compact "Record scrap" -- Source (Not put away / a
 * specific Bin) / Qty / Reason, scoped to one cohort. Mirrors
 * `MoveStockForm`'s own compact shape exactly. */
function ScrapForm({
  cohortId, farmId, buckets, onDone,
}: {
  cohortId: string;
  farmId: string;
  buckets: { location_id: string | null; label: string; balance: string }[];
  onDone: () => void;
}) {
  const [sourceKey, setSourceKey] = useState(buckets[0] ? (buckets[0].location_id ?? "not_put_away") : "");
  const [quantity, setQuantity] = useState("");
  const [reason, setReason] = useState("");
  const [error, setError] = useState<AppError | null>(null);
  const scrapMutation = useRecordInventoryScrap();

  return (
    <div className="flex flex-col gap-2 rounded-lg border border-wl-border bg-wl-surface p-3">
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
        <label className="flex flex-col gap-1">
          <span className={labelClass}>Source</span>
          <select className={inputClass} value={sourceKey} onChange={(e) => setSourceKey(e.target.value)}>
            {buckets.map((b) => (
              <option key={b.location_id ?? "not_put_away"} value={b.location_id ?? "not_put_away"}>
                {b.label} ({b.balance})
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1">
          <span className={labelClass}>Quantity</span>
          <input
            className={inputClass} type="number" min="0" step="any" value={quantity}
            onChange={(e) => setQuantity(e.target.value)}
          />
        </label>
        <label className="flex flex-col gap-1">
          <span className={labelClass}>Reason</span>
          <input className={inputClass} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. damaged packaging" />
        </label>
      </div>

      {error && <p className="rounded-md border border-wl-border bg-wl-flag-bg p-2 text-xs text-wl-flag-fg">{error.message}</p>}

      <div className="flex gap-2">
        <Button
          type="button" variant="primary"
          disabled={scrapMutation.isPending || !sourceKey || !quantity || Number(quantity) <= 0 || !reason.trim()}
          onClick={() => {
            setError(null);
            const isNotPutAway = sourceKey === "not_put_away";
            scrapMutation.mutate(
              {
                farmId,
                payload: {
                  client_command_id: crypto.randomUUID(),
                  source_kind: isNotPutAway ? "not_put_away" : "store_bin",
                  inventory_quantity_cohort_id: cohortId,
                  source_location_id: isNotPutAway ? null : sourceKey,
                  quantity, reason: reason.trim(), effective_time: new Date().toISOString(),
                },
              },
              { onSuccess: () => { setQuantity(""); setReason(""); onDone(); }, onError: (err) => setError(asAppError(err)) },
            );
          }}
        >
          {scrapMutation.isPending ? "Recording…" : "Record scrap"}
        </Button>
        <Button type="button" variant="secondary" onClick={onDone} disabled={scrapMutation.isPending}>
          Cancel
        </Button>
      </div>
    </div>
  );
}

/** One cohort's own physical custody -- Not put away / per-Bin balances --
 * plus its Move stock / Scrap actions. Rendered as one flat row inside the
 * single selected-stock panel (PILOT-UX-003), never as a further nested
 * `<table>` inside a table row.
 *
 * PILOT-BLOCKER-010 R3: `moveCommand`/`transferMutation` are page-level and
 * shared across every cohort row on the page -- only one Move can be
 * in-flight/unresolved at a time. `showMoveForm` re-derives "is this row's
 * form the one an unresolved command belongs to" from the frozen payload's
 * own `inventory_quantity_cohort_id`, not from local `moving` state alone --
 * local state resets to `false` on remount (e.g. the operator switched to a
 * different Item and back), but the frozen command must still reappear here
 * if this is the cohort it belongs to. */
function CohortCustodyRow({
  cohortId, farmId, activeBins, moveCommand, transferMutation,
}: {
  cohortId: string;
  farmId: string;
  activeBins: { id: string; label: string }[];
  moveCommand: UseFrozenSubmissionResult<InventoryStorageTransferCreate>;
  transferMutation: ReturnType<typeof useRecordInventoryStorageTransfer>;
}) {
  const breakdownQuery = useCohortStorageBreakdown(cohortId);
  const [moving, setMoving] = useState(false);
  const [scrapping, setScrapping] = useState(false);
  const buckets = breakdownQuery.data?.buckets ?? [];
  const binBuckets = buckets.filter((b) => b.location_id !== null) as { location_id: string; label: string; balance: string }[];

  const ownsUnresolvedMove = moveCommand.frozenPayload?.inventory_quantity_cohort_id === cohortId;
  const showMoveForm = (moving || ownsUnresolvedMove) && binBuckets.length > 0;
  // A second Move must never be opened while one is still in-flight/unknown
  // elsewhere -- `moveCommand`/`transferMutation` are shared, single-slot
  // page state, not a queue.
  const moveBlockedByOtherCommand = moveCommand.outcome !== "editing" && !ownsUnresolvedMove;

  return (
    <div className="flex flex-col gap-1.5 rounded-lg border border-wl-border bg-wl-surface-raised p-2.5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="text-xs text-wl-text-secondary">
          {breakdownQuery.isLoading
            ? "Loading custody…"
            : breakdownQuery.isError
              ? "Custody detail unavailable — retry"
              : buckets.length === 0
                ? "Nothing recorded"
                : buckets.map((b) => `${b.label}: ${b.balance}`).join(" · ")}
        </span>
        {!breakdownQuery.isLoading && !breakdownQuery.isError && (
          <div className="flex gap-2">
            {binBuckets.length > 0 && !showMoveForm && (
              <button
                type="button"
                className="text-xs font-medium text-wl-brand hover:underline disabled:cursor-not-allowed disabled:text-wl-text-tertiary disabled:no-underline"
                onClick={() => setMoving(true)}
                disabled={moveBlockedByOtherCommand}
                title={moveBlockedByOtherCommand ? "Finish or retry the in-progress Move first" : undefined}
              >
                Move stock
              </button>
            )}
            {buckets.length > 0 && !scrapping && (
              <button type="button" className="text-xs font-medium text-wl-brand hover:underline" onClick={() => setScrapping(true)}>
                Scrap
              </button>
            )}
          </div>
        )}
      </div>
      {showMoveForm && (
        <MoveStockForm
          cohortId={cohortId}
          farmId={farmId}
          fromBins={binBuckets.map((b) => ({ id: b.location_id, label: b.label, balance: b.balance }))}
          toBins={activeBins}
          onDone={() => setMoving(false)}
          command={moveCommand}
          transferMutation={transferMutation}
        />
      )}
      {scrapping && buckets.length > 0 && (
        <ScrapForm cohortId={cohortId} farmId={farmId} buckets={buckets} onDone={() => setScrapping(false)} />
      )}
    </div>
  );
}

/** The ONE selected-stock panel (PILOT-UX-003): everything about the item
 * currently selected in the Farm table -- Farm-scoped detail not already on
 * the row (Issued to operations, Not put away company-wide), then each
 * contributing cohort's own custody -- replacing the previous nested
 * table-inside-a-table-row structure with one flat panel. Cohort/bin detail
 * is fetched only for the selected item (`useItemExistenceProvenance`) and
 * only for its own cohorts (`useCohortStorageBreakdown`, one per cohort
 * actually shown here) -- never eagerly across the whole Inventory list. */
function SelectedStockPanel({
  itemId, itemName, farmId, uomCode, activeBins, farmNameById, exceptionStateByCohortId, moveCommand, transferMutation,
}: {
  itemId: string;
  itemName: string;
  farmId: string;
  uomCode: string | undefined;
  activeBins: { id: string; label: string }[];
  farmNameById: Map<string, string>;
  exceptionStateByCohortId: Map<string, string>;
  moveCommand: UseFrozenSubmissionResult<InventoryStorageTransferCreate>;
  transferMutation: ReturnType<typeof useRecordInventoryStorageTransfer>;
}) {
  const availabilityQuery = useItemFarmAvailability(farmId, itemId);
  const notPutAwayQuery = useItemStorageBreakdown(itemId);
  const provenanceQuery = useItemExistenceProvenance(itemId);
  const fmt = (v: string | undefined) => (v === undefined ? "…" : uomCode ? `${v} ${uomCode}` : v);
  const rows = provenanceQuery.data ?? [];

  return (
    <div className="flex flex-col gap-3 rounded-xl border border-wl-border bg-wl-surface-sunken p-3">
      <h3 className="text-sm font-semibold text-wl-text">Selected: {itemName}</h3>
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-wl-text-secondary">
        <span>
          Issued to operations (this Farm):{" "}
          <span className="font-medium text-wl-text">
            {availabilityQuery.isError ? "Unavailable — retry" : fmt(availabilityQuery.data?.issued_to_operations_quantity)}
          </span>
        </span>
        <span>
          Not put away (company-wide):{" "}
          <span className="font-medium text-wl-text">
            {notPutAwayQuery.isError ? "Unavailable — retry" : fmt(notPutAwayQuery.data?.not_put_away_quantity)}
          </span>
        </span>
      </div>

      <div>
        <h4 className="mb-1.5 text-xs font-semibold text-wl-text-secondary">Contributing lots / cohorts</h4>
        {provenanceQuery.isLoading ? (
          <p className="text-sm text-wl-text-secondary">Loading…</p>
        ) : provenanceQuery.isError ? (
          <p className="text-sm text-wl-flag-fg">Could not load contributing cohorts — retry.</p>
        ) : rows.length === 0 ? (
          <p className="text-sm text-wl-text-secondary">No cohorts contribute to this total.</p>
        ) : (
          <ul className="flex flex-col gap-2">
            {rows.map((row) => {
              const exceptionState = exceptionStateByCohortId.get(row.inventory_quantity_cohort_id);
              const exceptionReason = exceptionState ? EXCEPTION_REASON_LABEL[exceptionState] ?? exceptionState : null;
              return (
                <li key={row.inventory_quantity_cohort_id} className="flex flex-col gap-1.5">
                  <div className="flex flex-wrap items-baseline justify-between gap-2 text-xs">
                    <span className="text-wl-text">
                      Received at{" "}
                      <span className="font-medium">
                        {farmNameById.get(row.received_at_farm_id) ?? `Farm ${row.received_at_farm_id.slice(0, 8)}`}
                      </span>
                      {exceptionReason && (
                        <span className="ml-2 inline-flex w-fit items-center rounded-full bg-wl-hold-bg px-2 py-0.5 text-[11px] font-medium text-wl-hold-fg">
                          {exceptionReason}
                        </span>
                      )}
                    </span>
                    <span className="font-medium tabular-nums text-wl-text">{row.balance}{uomCode ? ` ${uomCode}` : ""}</span>
                  </div>
                  <CohortCustodyRow
                    cohortId={row.inventory_quantity_cohort_id}
                    farmId={farmId}
                    activeBins={activeBins}
                    moveCommand={moveCommand}
                    transferMutation={transferMutation}
                  />
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </div>
  );
}

/** One row of the primary, Farm-scoped operational table -- Available to
 * issue / In store / Reserved, all from the one `useItemFarmAvailability`
 * read (never a separate call per column). */
function FarmScopedCells({ itemId, farmId, uomCode }: { itemId: string; farmId: string; uomCode: string | undefined }) {
  const availabilityQuery = useItemFarmAvailability(farmId, itemId);
  const fmt = (v: string | undefined) => (uomCode ? `${v} ${uomCode}` : v);
  if (availabilityQuery.isLoading) {
    return (
      <>
        <td className="p-3 text-wl-text-secondary">…</td>
        <td className="p-3 text-wl-text-secondary">…</td>
        <td className="p-3 text-wl-text-secondary">…</td>
      </>
    );
  }
  if (availabilityQuery.isError) {
    return (
      <>
        <td className="p-3 text-wl-flag-fg">Unavailable</td>
        <td className="p-3 text-wl-flag-fg">Unavailable</td>
        <td className="p-3 text-wl-flag-fg">Unavailable</td>
      </>
    );
  }
  return (
    <>
      <td className="p-3 tabular-nums text-wl-text">{fmt(availabilityQuery.data?.available_to_issue_quantity)}</td>
      <td className="p-3 tabular-nums text-wl-text">{fmt(availabilityQuery.data?.in_store_quantity)}</td>
      <td className="p-3 tabular-nums text-wl-text">{fmt(availabilityQuery.data?.reserved_quantity)}</td>
    </>
  );
}

/** STORE-INV-002A.2/002B: Farm-scoped operational stock -- Available to
 * issue / In store / Reserved / Attention, one row per active Item -- is the
 * default, primary view (PILOT-UX-003: routine daily operation defaults to
 * THIS Farm). Company-wide Existence/Usable totals are a distinct,
 * visually-secondary, collapsed-by-default section below, never mixed into
 * the same columns as this Farm's own custody. Selecting a row opens the one
 * `SelectedStockPanel` below the table with that Item's contributing
 * cohorts/Bins and Move/Scrap actions -- replacing the previous
 * table-nested-inside-a-table-row structure. */
export default function StoreInventoryInventoryPage() {
  const { farmId } = useParams<{ farmId: string }>();
  const itemsQuery = useInventoryItems({ status: "active" });
  const items = itemsQuery.data ?? [];
  const uomsQuery = useUoms();
  const uomsById = new Map((uomsQuery.data ?? []).map((u) => [u.id, u.code]));
  const [selectedItemId, setSelectedItemId] = useState<string | null>(null);
  const [companyWideOpen, setCompanyWideOpen] = useState(false);
  const treeQuery = useLocationsTree(farmId);
  const activeBins = activeBinsWithPaths(treeQuery.data ?? []);
  const farmsQuery = useFarms();
  const farmNameById = new Map((farmsQuery.data ?? []).map((f) => [f.id, f.name]));

  // PILOT-BLOCKER-010 R3: owned HERE, above every disposable per-Item detail
  // panel/form instance, so an unresolved Move survives Hide detail,
  // switching the selected Item, or any query refresh that would otherwise
  // unmount `MoveStockForm`/`CohortCustodyRow`. See `MoveRecoveryBanner`
  // below, the stable recovery surface this ownership move makes possible.
  const transferMutation = useRecordInventoryStorageTransfer();
  const moveCommand = useFrozenSubmission<InventoryStorageTransferCreate>();

  // ONE company-wide read for the whole page (never per-item/per-cohort) --
  // an Item has "Attention" here only if one of its cohorts received at
  // THIS Farm carries a real authoritative exception state (R7). The
  // Quality work queue itself lists every positive-balance cohort
  // company-wide, RELEASED/HOLD_RELEASED included -- mere membership was
  // the pre-fix defect, never treated as an exception on its own.
  //
  // R6 residual (unchanged pre-existing choice, not solved by this ticket):
  // `received_at_farm_id` is receipt provenance only, never authoritative
  // current custody (docs/domain/STORE_INVENTORY_MODEL.md §7) -- so this
  // Farm filter is a heuristic ("likely still near where it was received"),
  // not a custody-authoritative scope. Precise current-Farm Attention scope
  // needs custody/location-farm metadata this read model does not expose.
  const qualityQueueQuery = useQualityWorkQueue();
  const hasQualityQueueData = qualityQueueQuery.data !== undefined;
  const exceptionRowsForFarm = hasQualityQueueData
    ? (qualityQueueQuery.data ?? []).filter(
        (row) => row.received_at_farm_id === farmId && EXCEPTION_STATES.has(row.current_state),
      )
    : [];
  const exceptionReasonsByItemId = new Map<string, Set<string>>();
  exceptionRowsForFarm.forEach((row) => {
    const reasons = exceptionReasonsByItemId.get(row.inventory_item_id) ?? new Set<string>();
    reasons.add(row.current_state);
    exceptionReasonsByItemId.set(row.inventory_item_id, reasons);
  });
  // Company-wide (not Farm-filtered) -- feeds the selected-item panel, which
  // shows each contributing cohort's own exception regardless of which Farm
  // received it.
  const exceptionStateByCohortId = new Map(
    (qualityQueueQuery.data ?? [])
      .filter((row) => EXCEPTION_STATES.has(row.current_state))
      .map((row) => [row.inventory_quantity_cohort_id, row.current_state]),
  );

  // Deferred until the operator actually opens the section -- never fetched
  // eagerly across every active Item just to render a collapsed summary.
  const companyWideSummary = useItemsExistenceSummary(items.map((i) => i.id), companyWideOpen);

  const selectedItem = items.find((i) => i.id === selectedItemId) ?? null;

  return (
    <div>
      <PageHeader
        title="Inventory"
        description="This Farm's stock, available to issue right now. Company-wide totals are a separate summary below."
        breadcrumbs={
          <Breadcrumbs
            items={[
              { label: "Home", href: `/farms/${farmId}` },
              { label: "Store & Inventory", href: `/farms/${farmId}/store-inventory` },
              { label: "Inventory" },
            ]}
          />
        }
      />
      <StoreSubNav farmId={farmId} />

      {moveCommand.outcome === "uncertain" && moveCommand.frozenPayload && (
        <MoveRecoveryBanner
          frozenPayload={moveCommand.frozenPayload}
          activeBins={activeBins}
          onRetry={() => {
            const payload = moveCommand.retry();
            if (!payload) return;
            transferMutation.mutate(
              { farmId, payload },
              {
                onSuccess: () => moveCommand.handleSuccess(),
                onError: (err) => moveCommand.handleError(err instanceof AppError ? err : new AppError("server_error", "Something went wrong. Please try again.")),
              },
            );
          }}
        />
      )}

      {itemsQuery.isLoading ? (
        <p className="text-sm text-wl-text-secondary">Loading…</p>
      ) : itemsQuery.isError ? (
        <p className="text-sm text-wl-flag-fg">Could not load Inventory Items — retry.</p>
      ) : items.length === 0 ? (
        <p className="text-sm text-wl-text">No active Inventory Items configured yet.</p>
      ) : (
        <div className="flex flex-col gap-4">
          <div className="overflow-x-auto rounded-xl border border-wl-border bg-wl-surface-raised">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-wl-border text-left text-wl-text-secondary">
                  <th className="p-3 font-medium">Item</th>
                  <th className="p-3 font-medium">Available to issue</th>
                  <th className="p-3 font-medium">In store</th>
                  <th className="p-3 font-medium">Reserved</th>
                  <th className="p-3 font-medium">Attention</th>
                  <th className="p-3 font-medium" />
                </tr>
              </thead>
              <tbody>
                {items.map((item) => {
                  const isSelected = selectedItemId === item.id;
                  const uomCode = uomsById.get(item.base_uom_id);
                  const exceptionReasons = exceptionReasonsByItemId.get(item.id);
                  return (
                    <tr
                      key={item.id}
                      className={`cursor-pointer border-b border-wl-border last:border-0 hover:bg-wl-surface-hover ${isSelected ? "bg-wl-brand-subtle" : ""}`}
                      onClick={() => setSelectedItemId(isSelected ? null : item.id)}
                    >
                      <td className="p-3 font-medium text-wl-text">
                        {item.name}
                        {item.lot_tracking_required && (
                          <span className="ml-2 rounded bg-wl-surface-sunken px-1.5 py-0.5 text-[10px] uppercase text-wl-text-secondary">
                            lot-tracked
                          </span>
                        )}
                      </td>
                      <FarmScopedCells itemId={item.id} farmId={farmId} uomCode={uomCode} />
                      <td className="p-3">
                        {qualityQueueQuery.isLoading && !hasQualityQueueData ? (
                          <span className="text-xs text-wl-text-secondary">…</span>
                        ) : qualityQueueQuery.isError && !hasQualityQueueData ? (
                          <span className="text-xs text-wl-flag-fg">Unavailable</span>
                        ) : exceptionReasons && exceptionReasons.size > 0 ? (
                          <span
                            title={[...exceptionReasons].map((s) => EXCEPTION_REASON_LABEL[s] ?? s).join(", ")}
                            className="inline-flex w-fit items-center rounded-full bg-wl-hold-bg px-2 py-0.5 text-xs font-medium text-wl-hold-fg"
                          >
                            {exceptionReasons.size === 1
                              ? EXCEPTION_REASON_LABEL[[...exceptionReasons][0]] ?? [...exceptionReasons][0]
                              : `${exceptionReasons.size} exceptions`}
                          </span>
                        ) : (
                          <span className="text-xs text-wl-text-secondary">—</span>
                        )}
                      </td>
                      <td className="p-3 text-right">
                        <button
                          type="button"
                          className="text-xs font-medium text-wl-brand hover:underline"
                          onClick={(e) => {
                            e.stopPropagation();
                            setSelectedItemId(isSelected ? null : item.id);
                          }}
                        >
                          {isSelected ? "Hide detail" : "Show detail"}
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {selectedItem && (
            <SelectedStockPanel
              itemId={selectedItem.id}
              itemName={selectedItem.name}
              farmId={farmId}
              uomCode={uomsById.get(selectedItem.base_uom_id)}
              activeBins={activeBins}
              farmNameById={farmNameById}
              exceptionStateByCohortId={exceptionStateByCohortId}
              moveCommand={moveCommand}
              transferMutation={transferMutation}
            />
          )}

          <div className="rounded-xl border border-wl-border bg-wl-surface-raised">
            <button
              type="button"
              className="w-full p-3 text-left text-sm font-medium text-wl-text-secondary hover:bg-wl-surface-hover"
              onClick={() => setCompanyWideOpen((open) => !open)}
              aria-expanded={companyWideOpen}
            >
              {companyWideOpen ? "▾" : "▸"} Company-wide totals (all Farms)
            </button>
            <div className="overflow-x-auto border-t border-wl-border" hidden={!companyWideOpen}>
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-wl-border text-left text-wl-text-secondary">
                    <th className="p-3 font-medium">Item</th>
                    <th className="p-3 font-medium">Exists</th>
                    <th className="p-3 font-medium">Usable</th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((item) => {
                    const row = companyWideSummary.byItemId[item.id];
                    const uomCode = uomsById.get(item.base_uom_id);
                    return (
                      <tr key={item.id} className="border-b border-wl-border last:border-0">
                        <td className="p-3 text-wl-text">{item.name}</td>
                        <td className="p-3 tabular-nums text-wl-text-secondary">
                          {!companyWideOpen || companyWideSummary.isLoading
                            ? "…"
                            : row?.existing !== undefined && row.existing !== null
                              ? `${row.existing} ${uomCode ?? ""}`.trim()
                              : "0"}
                        </td>
                        <td className="p-3 tabular-nums text-wl-text-secondary">
                          {!companyWideOpen || companyWideSummary.isLoading
                            ? "…"
                            : row?.usable !== undefined && row.usable !== null
                              ? `${row.usable} ${uomCode ?? ""}`.trim()
                              : "0"}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
