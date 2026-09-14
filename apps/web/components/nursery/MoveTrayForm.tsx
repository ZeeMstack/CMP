"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useEffect, useRef, useState } from "react";
import { useForm } from "react-hook-form";

import { EmptyState } from "@/components/EmptyState";
import { Button } from "@/components/ui/Button";
import type { GerminationTrayRead, PlaceTrayCreate } from "@/lib/api/client";
import { AppError } from "@/lib/errors/adapter";
import { useAvailableTrolleys, useGerminationTrays, useTrolleyLevels } from "@/lib/query/hooks";
import {
  DEFAULT_PLACE_TRAY_FORM_VALUES,
  buildPlaceTrayPayload,
  placeTrayFormSchema,
  type PlaceTrayFormValues,
} from "@/lib/validation/germination";

const inputClass =
  "min-h-11 w-full rounded-md border border-wl-border bg-wl-surface-raised px-3 text-sm text-wl-text focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-wl-focus";
const labelClass = "block text-sm font-medium text-wl-text";
const errorClass = "text-xs text-danger-700";

function Field({ label, error, children }: { label: string; error?: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1">
      <span className={labelClass}>{label}</span>
      {children}
      {error && <span className={errorClass}>{error}</span>}
    </label>
  );
}

function nowDateAndTime() {
  const now = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  return {
    date: `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`,
    time: `${pad(now.getHours())}:${pad(now.getMinutes())}`,
  };
}

/** PILOT-BLOCKER-010 R4: one tray's own status within a frozen bulk run --
 * a truthful record, not an optimistic one. Identified by `trayId` (stable)
 * everywhere, never by its position in any array -- the live eligible-tray
 * query reorders/shrinks as each move commits (its own `onSuccess`
 * invalidates the same query the board itself reads), so an index would
 * silently drift out from under a resuming "Continue"/"Retry" click.
 *
 * `"unknown"` (network/timeout/5xx -- the server's response was never
 * received) is a DIFFERENT case from `"failed"` (a definitive domain
 * rejection): an unknown outcome must never be labeled "could not be
 * moved", and retrying it must replay the EXACT frozen
 * `client_command_id`/payload, never a fresh one -- `frozenPayload` is kept
 * only for `"unknown"`, cleared on a definitive `"failed"` (a fresh logical
 * command is fine there) or `"confirmed"`. */
type RunEntryStatus = "not_attempted" | "submitting" | "confirmed" | "unknown" | "failed";

interface RunEntry {
  trayId: string;
  trayCode: string;
  seedsSown: number;
  status: RunEntryStatus;
  clientCommandId: string | null;
  frozenPayload: PlaceTrayCreate | null;
  failedReason: string | null;
}

/** PILOT-BLOCKER-010 R4: the whole bulk run, frozen the moment the FIRST
 * tray in it is submitted (via "Move All" or an individual row "Move") --
 * `entries` is then the sole source of truth for which trays this run
 * covers and their status; the live `trays` prop (whatever
 * `useGerminationTrays` currently returns) is used only for validation/
 * capacity checks and for a NEW run once this one fully resolves, never to
 * rebuild `entries`. `trolleyId`/`levelId`/`reason` are the run's own frozen
 * destination context -- fixed once the run starts, so every entry in it
 * targets the same place regardless of what the (now-disabled) destination
 * fields might otherwise show. */
interface FrozenRun {
  batchCode: string;
  trolleyId: string;
  trolleyCode: string;
  levelId: string;
  levelCode: string;
  reason: string;
  entries: RunEntry[];
}

function isUncertainSubmitError(err: unknown): boolean {
  return err instanceof AppError && (err.kind === "network_error" || err.kind === "server_error");
}

/** The destination context a run freezes at start -- passed up from
 * `BulkMoveBoard`'s own (pre-run) selection state the first time a
 * submission actually happens, since `MoveTrayForm` doesn't otherwise know
 * what the board's Trolley/Level/Reason fields currently hold. */
interface RunDestination {
  trolleyId: string;
  trolleyCode: string;
  levelId: string;
  levelCode: string;
  reason: string;
  batchCode: string;
}

/** PILOT-UX-001 (CTO correction): a Sowing batch commonly spans 5-50+ Seed
 * Trays. The backend's `place_tray` command (`PlaceTrayCreate`) accepts
 * exactly one `tray_id` per call -- confirmed no bulk/list-based placement
 * command exists anywhere in this domain (movements and transplant are
 * likewise single-entity). Redesigning that is out of scope here, so this
 * board keeps the Batch and destination (Trolley/Level) selected ONCE.
 * "Move All" orchestrates the SAME single-tray command sequentially with
 * its own idempotency key per call; a per-row "Move" stays available as a
 * manual/exception path. A follow-up candidate (reported, not built here):
 * a real bulk placement command if/when the backend adds one.
 *
 * PILOT-BLOCKER-010 R4: the run itself (`frozenRun`) is owned by the
 * PARENT (`MoveTrayForm`), not this component -- this board must be able to
 * survive the live eligible-tray count changing (it does, every time a
 * `place_tray` call in this very run succeeds and invalidates the query
 * this board would otherwise be gated on) without losing an unresolved
 * command. This component itself never unmounts mid-run any more; see
 * `showBulkBoard` in `MoveTrayForm` below. */
function BulkMoveBoard({
  farmId, batchCode, trays, frozenRun, hasUnknownEntry, isRunningAny, onSubmitEntry, onRunAll, onSwitchToSingle,
  onCancel, onSetUpTrolley,
}: {
  farmId: string;
  batchCode: string;
  /** LIVE eligible trays for this Batch -- used only (a) before any run has
   * started, to browse/select trays to move, and (b) as the entry list a
   * NEW run freezes from the moment it starts. Once `frozenRun` is non-null,
   * rendering uses `frozenRun.entries` instead, never this list again, so a
   * refetch that shrinks/reorders it can never rewrite run history. */
  trays: GerminationTrayRead[];
  frozenRun: FrozenRun | null;
  hasUnknownEntry: boolean;
  isRunningAny: boolean;
  onSubmitEntry: (trayId: string, destination: RunDestination) => void;
  onRunAll: (destination: RunDestination) => void;
  onSwitchToSingle: () => void;
  onCancel: () => void;
  onSetUpTrolley?: () => void;
}) {
  const [trolleyId, setTrolleyId] = useState("");
  const [levelId, setLevelId] = useState("");
  const [reason, setReason] = useState("");
  const [showRowTable, setShowRowTable] = useState(false);

  const trolleysQuery = useAvailableTrolleys(farmId);
  const trolleys = trolleysQuery.data ?? [];
  const levelsQuery = useTrolleyLevels(farmId, trolleyId);
  const levels = levelsQuery.data ?? [];
  const selectedLevel = levels.find((l) => l.id === levelId) ?? null;
  const destinationReady = Boolean(trolleyId && levelId);
  const levelIsFull = selectedLevel !== null && (selectedLevel.available_capacity ?? 0) <= 0;
  // Once a run exists, its own frozen destination is authoritative for
  // display -- the live selects below are disabled the moment `frozenRun`
  // exists (never re-targetable mid-run), so they can never diverge from it.
  const trolleyCode = trolleys.find((t) => t.id === trolleyId)?.code ?? "";
  const levelCode = selectedLevel?.code ?? "";

  // PILOT-BLOCKER-010: the display list is the frozen run's own entries once
  // a run exists -- confirmed trays and not-yet-attempted trays both stay
  // visible here regardless of what the live `trays` query currently
  // returns (a confirmed tray legitimately drops out of the live eligible
  // list once its state flips server-side; it must not also vanish from
  // this table). Before any run starts, this is simply a live projection of
  // `trays`, unchanged from the pre-fix behavior.
  const displayEntries: RunEntry[] = frozenRun
    ? frozenRun.entries
    : trays.map((t) => ({
        trayId: t.tray.id, trayCode: t.tray.code, seedsSown: t.seeds_sown, status: "not_attempted",
        clientCommandId: null, frozenPayload: null, failedReason: null,
      }));
  const confirmedCount = displayEntries.filter((e) => e.status === "confirmed").length;
  const allConfirmed = displayEntries.length > 0 && confirmedCount === displayEntries.length;
  const blockingEntry = displayEntries.find((e) => e.status === "unknown" || e.status === "failed");
  const submittingEntry = displayEntries.find((e) => e.status === "submitting");
  const remainingCount = displayEntries.filter((e) => e.status !== "confirmed").length;
  // PILOT-UX-001 (CTO correction): use ONLY the already-fetched Level
  // capacity to rule out an obviously-impossible run before starting --
  // never a re-implementation of backend capacity logic, which remains
  // authoritative for every individual `place_tray` call regardless. Once a
  // run is under way, this revalidates against the LIVE Level capacity
  // (refetched after every confirmed move) compared to the run's own
  // REMAINING entries -- never the frozen run's original total, and never
  // discarding the frozen run to do it.
  const capacityInsufficient =
    selectedLevel !== null && selectedLevel.mode === "direct" && (selectedLevel.available_capacity ?? 0) < remainingCount;

  const destination: RunDestination = { trolleyId, trolleyCode, levelId, levelCode, reason, batchCode };

  return (
    <div className="flex flex-col gap-6">
      <p className="rounded-md border border-wl-border-strong bg-wl-brand-subtle px-3 py-2 text-xs text-wl-brand">
        Continuing from Sowing — Batch {batchCode}, {displayEntries.length} eligible Seed Tray
        {displayEntries.length === 1 ? "" : "s"}.{" "}
        <button
          type="button" className="font-medium underline" onClick={onSwitchToSingle}
          disabled={isRunningAny || hasUnknownEntry}
        >
          Move a single Seed Tray instead
        </button>
      </p>

      {hasUnknownEntry && (
        <div role="alert" className="rounded-md border border-amber-300 bg-amber-50 p-3 text-xs text-amber-900">
          <p className="font-semibold">RESULT UNKNOWN — RETRY/RECONCILE REQUIRED</p>
          <p>
            Tray {blockingEntry?.trayCode}: we couldn&apos;t confirm whether this Move was recorded. Do not repeat
            this operation as a new transaction -- Retry sends the exact same submitted values again.
          </p>
        </div>
      )}

      <fieldset className="flex flex-col gap-4 rounded-xl border border-wl-border bg-wl-surface-raised p-4">
        <legend className="px-1 text-sm font-semibold text-wl-text">Destination (applies to every move below)</legend>
        {trolleysQuery.isSuccess && trolleys.length === 0 ? (
          <EmptyState
            title="No Germination Trolley placed"
            description="No Trolleys are currently placed in a Germination Chamber. Place a Trolley before moving Seed Trays onto it."
            action={
              onSetUpTrolley ? (
                <Button type="button" variant="secondary" onClick={onSetUpTrolley}>
                  Place Trolley
                </Button>
              ) : undefined
            }
          />
        ) : (
          <>
            <Field label="Trolley">
              <select
                className={inputClass}
                value={trolleyId}
                // PILOT-BLOCKER-010: once a run exists, its destination is
                // frozen -- never re-targetable mid-run, not merely while
                // uncertain (every entry in the run must go to the same
                // place, including any not yet attempted).
                disabled={Boolean(frozenRun) || isRunningAny}
                onChange={(e) => {
                  setTrolleyId(e.target.value);
                  setLevelId("");
                }}
              >
                <option value="">Select a Trolley…</option>
                {trolleys.map((trolley) => (
                  <option key={trolley.id} value={trolley.id}>
                    {trolley.code} — {trolley.chamber.code} ({trolley.available_capacity} of{" "}
                    {trolley.total_capacity} free)
                  </option>
                ))}
              </select>
            </Field>
            {trolleyId && (
              <Field label="Level">
                <select
                  className={inputClass}
                  value={levelId}
                  disabled={Boolean(frozenRun) || isRunningAny}
                  onChange={(e) => setLevelId(e.target.value)}
                >
                  <option value="">Select a Level…</option>
                  {levels.map((level) => {
                    const isFull = level.mode !== "invalid" && (level.available_capacity ?? 0) <= 0;
                    // Bulk moves target one shared Level per pass; a legacy
                    // Level still needs its own per-Slot choice, so it stays
                    // out of this fast path -- move it via the single-tray
                    // flow instead (never silently mis-targeted).
                    const isLegacy = level.mode === "legacy";
                    const disabled = level.mode === "invalid" || isFull || isLegacy;
                    const suffix =
                      level.mode === "invalid"
                        ? " (not configured)"
                        : isFull
                          ? " (full)"
                          : isLegacy
                            ? " (needs individual placement)"
                            : ` (${level.available_capacity} of ${level.capacity} free)`;
                    return (
                      <option key={level.id} value={level.id} disabled={disabled}>
                        {level.code}
                        {suffix}
                      </option>
                    );
                  })}
                </select>
              </Field>
            )}
          </>
        )}
      </fieldset>

      <fieldset className="flex flex-col gap-4 rounded-xl border border-wl-border bg-wl-surface-raised p-4">
        <legend className="px-1 text-sm font-semibold text-wl-text">Reason (optional, applies to every move below)</legend>
        <textarea
          className={`${inputClass} min-h-16`}
          rows={2}
          value={reason}
          disabled={Boolean(frozenRun) || isRunningAny}
          onChange={(e) => setReason(e.target.value)}
        />
      </fieldset>

      <div className="flex flex-col gap-3 border-t border-wl-border pt-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <p className="text-sm font-medium text-wl-text">
              {confirmedCount > 0 && `${confirmedCount} of `}
              {displayEntries.length} tray{displayEntries.length === 1 ? "" : "s"}
              {confirmedCount > 0 ? " moved" : " ready"}
            </p>
            {!destinationReady && !frozenRun && (
              <p className="text-xs text-wl-text-secondary">Choose a Trolley and Level to enable Move All.</p>
            )}
          </div>
          {!allConfirmed && (
            <div className="flex flex-wrap gap-2">
              <Button
                type="button"
                variant="primary"
                disabled={!destinationReady || isRunningAny || capacityInsufficient}
                onClick={() => onRunAll(destination)}
              >
                {isRunningAny
                  ? `Moving ${confirmedCount + 1} of ${displayEntries.length}${submittingEntry ? ` (${submittingEntry.trayCode})` : ""}…`
                  : hasUnknownEntry
                    ? "Retry and Continue"
                    : blockingEntry
                      ? "Continue Remaining"
                      : `Move All ${displayEntries.length} Tray${displayEntries.length === 1 ? "" : "s"}`}
              </Button>
              <Button
                type="button" variant="secondary" disabled={isRunningAny}
                onClick={() => setShowRowTable((v) => !v)}
              >
                {showRowTable ? "Hide trays" : "Show trays"}
              </Button>
            </div>
          )}
        </div>
        {capacityInsufficient && selectedLevel && (
          <p className="text-xs text-danger-700">
            This Level only has {selectedLevel.available_capacity} of the {remainingCount} needed free positions.
            Choose a Level with more capacity, or move trays individually below.
          </p>
        )}
      </div>

      {allConfirmed && (
        <div className="flex flex-col gap-2 rounded-lg border border-wl-border-strong bg-wl-grow-bg p-3 text-sm text-wl-grow-fg">
          <p>
            {confirmedCount} tray{confirmedCount === 1 ? "" : "s"} moved to Trolley {frozenRun?.trolleyCode ?? trolleyCode} /
            Level {frozenRun?.levelCode ?? levelCode}
          </p>
          <Button type="button" variant="secondary" className="self-start" onClick={onCancel}>
            Continue
          </Button>
        </div>
      )}

      {blockingEntry && !hasUnknownEntry && (
        <div className="flex flex-col gap-2 rounded-lg border border-wl-border-strong bg-wl-flag-bg p-3 text-sm text-wl-flag-fg">
          <p>
            Tray {blockingEntry.trayCode} could not be moved: {blockingEntry.failedReason}
          </p>
        </div>
      )}

      {(showRowTable || blockingEntry) && (
        <div className="overflow-x-auto rounded-xl border border-wl-border bg-wl-surface-raised">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-wl-border bg-wl-surface-sunken text-xs uppercase text-wl-text-secondary">
              <tr>
                <th className="px-4 py-2 font-medium">Seed Tray</th>
                <th className="px-4 py-2 font-medium">Seeds sown</th>
                <th className="px-4 py-2 font-medium" />
              </tr>
            </thead>
            <tbody className="divide-y divide-wl-border">
              {displayEntries.map((entry) => (
                <tr key={entry.trayId}>
                  <td className="px-4 py-2 font-medium text-wl-text">{entry.trayCode}</td>
                  <td className="px-4 py-2 text-wl-text-secondary">{entry.seedsSown.toLocaleString()}</td>
                  <td className="px-4 py-2 text-right">
                    {entry.status === "confirmed" ? (
                      <span className="text-xs font-medium text-wl-grow-fg">Confirmed</span>
                    ) : (
                      <>
                        {entry.status === "unknown" && (
                          <p className="mb-1 text-xs text-amber-800">
                            Result not confirmed -- submitted, but the server&apos;s response was never received.
                          </p>
                        )}
                        {entry.status === "failed" && entry.failedReason && (
                          <p className="mb-1 text-xs text-danger-700">{entry.failedReason}</p>
                        )}
                        <Button
                          type="button"
                          variant={entry.status === "failed" || entry.status === "unknown" ? "secondary" : "primary"}
                          disabled={
                            !destinationReady || isRunningAny || entry.status === "submitting" ||
                            (entry.status === "not_attempted" && levelIsFull)
                          }
                          onClick={() => onSubmitEntry(entry.trayId, destination)}
                        >
                          {entry.status === "submitting"
                            ? "Moving…"
                            : entry.status === "failed" || entry.status === "unknown"
                              ? "Retry"
                              : "Move"}
                        </Button>
                      </>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div>
        <Button type="button" variant="secondary" onClick={onCancel} disabled={isRunningAny || hasUnknownEntry}>
          Done
        </Button>
      </div>
    </div>
  );
}

/** A Sown Seed Tray into a Level on a Trolley that is currently placed in a
 * Germination Chamber (enforced server-side -- the backend rejects a
 * Trolley that isn't currently in Germination, section 16).
 *
 * PILOT-UX-001B: the backend is authoritative for per-Level classification
 * (`legacy` / `direct` / `invalid`, via `useTrolleyLevels`) -- this form
 * consumes `mode` and never re-derives it from raw position structure.
 * A `direct` Level is itself the terminal selection (its own id is
 * submitted, no further step). A `legacy` Level still requires picking one
 * of its open child Slots, exactly as before. An `invalid` Level (or a
 * Level with zero remaining capacity) is shown, disabled, so an operator
 * can see it exists and why it cannot be used, but can never select it.
 *
 * Physical placement only; no biological Germination outcome field appears
 * here. */
export function MoveTrayForm({
  farmId, onSubmit, onCancel, isSubmitting, serverError, initialBatchId, onSetUpTrolley, onSubmitOne, initialTrayId,
}: {
  farmId: string;
  onSubmit: (payload: PlaceTrayCreate) => void;
  onCancel: () => void;
  isSubmitting: boolean;
  serverError?: string | null;
  // PILOT-UX-001: process continuity from Sowing -- when set, the Seed Tray
  // sown for this Batch is auto-selected once it is the only eligible match,
  // never guessed when more than one tray could apply.
  initialBatchId?: string | null;
  // PILOT-UX-001: lets the parent page reveal its own "Place Trolley" action
  // from this form's empty state, instead of a dead end.
  onSetUpTrolley?: () => void;
  // PILOT-UX-001 (CTO correction): a Promise-returning single-tray submit
  // used by the bulk board below for fast, reviewless sequential moves --
  // distinct from `onSubmit`, which closes the whole form on success (fine
  // for one tray, wrong for looping through many).
  onSubmitOne?: (payload: PlaceTrayCreate) => Promise<unknown>;
  // PILOT-UX-002B: the operator's worklist row already identifies one exact
  // Seed Tray -- when set, that Tray is frozen (no dropdown, never the bulk
  // board) so the operator is never asked to find/select it again. Distinct
  // from `initialBatchId`, which only narrows a Batch's several trays.
  initialTrayId?: string | null;
}) {
  const [step, setStep] = useState<"configure" | "review">("configure");
  const [clientCommandId] = useState(() => crypto.randomUUID());
  const [selectedTrolleyId, setSelectedTrolleyId] = useState("");
  const [selectedLevelId, setSelectedLevelId] = useState("");
  const [forceSingleMode, setForceSingleMode] = useState(false);

  // PILOT-BLOCKER-010 R4: the bulk run's OWN state, owned here -- one level
  // ABOVE `BulkMoveBoard`, which this fix makes non-disposable for the
  // duration of a run, but the run state is kept up here regardless so
  // nothing about its correctness depends on that. `frozenRunRef` is the
  // synchronous source of truth the sequential `runAll` loop reads/writes
  // (a `useState` setter's effect isn't visible until the next render,
  // which would be too late for the very next loop iteration); `frozenRun`
  // (state) exists purely to trigger re-renders so the board reflects it.
  const frozenRunRef = useRef<FrozenRun | null>(null);
  const [frozenRun, setFrozenRunState] = useState<FrozenRun | null>(null);
  function commitFrozenRun(run: FrozenRun | null) {
    frozenRunRef.current = run;
    setFrozenRunState(run);
  }
  function updateRunEntry(trayId: string, patch: Partial<RunEntry>) {
    const run = frozenRunRef.current;
    if (!run) return;
    commitFrozenRun({ ...run, entries: run.entries.map((e) => (e.trayId === trayId ? { ...e, ...patch } : e)) });
  }
  /** Only ever CREATES the run once, from whatever trays are currently
   * eligible for this Batch at that exact moment -- every later call is a
   * no-op returning the existing run untouched. This is what stops a
   * mid-run query refetch from ever rewriting run history: after this first
   * call, nothing reads `matchingBatchTrays` to decide run MEMBERSHIP again. */
  function ensureRunStarted(destination: RunDestination): FrozenRun {
    if (frozenRunRef.current) return frozenRunRef.current;
    const run: FrozenRun = {
      batchCode: destination.batchCode,
      trolleyId: destination.trolleyId, trolleyCode: destination.trolleyCode,
      levelId: destination.levelId, levelCode: destination.levelCode,
      reason: destination.reason,
      entries: matchingBatchTrays.map((t) => ({
        trayId: t.tray.id, trayCode: t.tray.code, seedsSown: t.seeds_sown, status: "not_attempted",
        clientCommandId: null, frozenPayload: null, failedReason: null,
      })),
    };
    commitFrozenRun(run);
    return run;
  }
  /** Submits exactly one run entry -- reused identically by a per-row
   * "Move"/"Retry" click and by `runAll`'s own loop, so there is only ever
   * one place that freezes/reuses a tray's `client_command_id`/payload. A
   * Retry re-enters this with the SAME entry already carrying its frozen
   * payload (only kept non-null while `"unknown"`), so it replays exactly,
   * never minting a fresh id. */
  async function submitRunEntry(trayId: string, destination: RunDestination) {
    const run = ensureRunStarted(destination);
    const entry = run.entries.find((e) => e.trayId === trayId) ?? frozenRunRef.current?.entries.find((e) => e.trayId === trayId);
    if (!entry || entry.status === "submitting" || entry.status === "confirmed" || !onSubmitOne) return;
    const clientCommandId = entry.clientCommandId ?? crypto.randomUUID();
    const payload: PlaceTrayCreate = entry.frozenPayload ?? {
      client_command_id: clientCommandId,
      tray_id: trayId,
      trolley_id: run.trolleyId,
      asset_position_id: run.levelId,
      effective_time: new Date().toISOString(),
      reason: run.reason.trim() || null,
    };
    updateRunEntry(trayId, { status: "submitting", clientCommandId, frozenPayload: payload });
    try {
      await onSubmitOne(payload);
      updateRunEntry(trayId, { status: "confirmed", frozenPayload: null, clientCommandId: null, failedReason: null });
    } catch (err) {
      const uncertain = isUncertainSubmitError(err);
      updateRunEntry(trayId, {
        // A definitive rejection lets the operator resubmit as a genuinely
        // new logical command (fresh id next time); an uncertain outcome
        // keeps the frozen command intact so Retry replays it exactly.
        status: uncertain ? "unknown" : "failed",
        frozenPayload: uncertain ? payload : null,
        clientCommandId: uncertain ? clientCommandId : null,
        failedReason:
          err instanceof AppError
            ? err.message
            : uncertain
              ? "Result not confirmed -- submitted, but the server's response was never received."
              : "Move failed. Try again.",
      });
    }
  }
  /** "Move All"/"Continue Remaining"/"Retry and Continue" are all the SAME
   * call -- it walks the frozen run's own entry order (never the live tray
   * array/an index into it), skips whatever is already `"confirmed"`, and
   * stops at the first `"unknown"`/`"failed"` result exactly like the
   * original sequential behavior (earlier successful calls already
   * committed and are never pretended to have rolled back). */
  async function runAll(destination: RunDestination) {
    const run = ensureRunStarted(destination);
    for (const entry of run.entries) {
      const current = frozenRunRef.current?.entries.find((e) => e.trayId === entry.trayId);
      if (!current || current.status === "confirmed") continue;
      await submitRunEntry(entry.trayId, destination);
      const after = frozenRunRef.current?.entries.find((e) => e.trayId === entry.trayId);
      if (after && (after.status === "unknown" || after.status === "failed")) return;
    }
  }
  const hasUnknownRunEntry = frozenRun?.entries.some((e) => e.status === "unknown") ?? false;
  const isRunningAny = frozenRun?.entries.some((e) => e.status === "submitting") ?? false;
  // PILOT-BLOCKER-010: defense in depth (mirrors `useQualityCommandDraft`'s
  // `close()`) -- even if some other path ever called these directly, an
  // unresolved run can never be silently abandoned this way.
  function guardedSwitchToSingle() {
    if (hasUnknownRunEntry || isRunningAny) return;
    setForceSingleMode(true);
  }
  function guardedDone() {
    if (hasUnknownRunEntry || isRunningAny) return;
    commitFrozenRun(null);
    onCancel();
  }

  const initial = nowDateAndTime();
  const {
    register, setValue, trigger, getValues, formState: { errors },
  } = useForm<PlaceTrayFormValues>({
    resolver: zodResolver(placeTrayFormSchema),
    defaultValues: { ...DEFAULT_PLACE_TRAY_FORM_VALUES, effective_date: initial.date, effective_time_of_day: initial.time },
    mode: "onBlur",
  });

  const traysQuery = useGerminationTrays(farmId);
  const eligibleTrays = (traysQuery.data ?? []).filter((t) => t.state !== "in_germination");
  const matchingBatchTrays = initialBatchId ? eligibleTrays.filter((t) => t.batch_id === initialBatchId) : [];
  // Continuity from Sowing: the incoming Batch's own trays surface first,
  // never hidden or re-filtered away -- every eligible tray stays selectable.
  const orderedEligibleTrays = initialBatchId
    ? [...matchingBatchTrays, ...eligibleTrays.filter((t) => t.batch_id !== initialBatchId)]
    : eligibleTrays;
  // PILOT-UX-002B: the worklist row already identifies one exact eligible
  // Tray -- frozen, not re-derived on every refetch, so a query refresh can
  // never silently retarget an open form onto a different assignment
  // (section 8/14). If the Tray is no longer eligible (moved, or another
  // operator already placed it), `frozenTray` simply comes back `undefined`
  // and the form shows a stale message instead of a broken/blank one.
  const frozenTray = initialTrayId ? eligibleTrays.find((t) => t.tray.id === initialTrayId) : null;
  const trolleysQuery = useAvailableTrolleys(farmId);
  const trolleys = trolleysQuery.data ?? [];
  const levelsQuery = useTrolleyLevels(farmId, selectedTrolleyId);
  const levels = levelsQuery.data ?? [];

  useEffect(() => {
    if (initialTrayId) return;
    if (matchingBatchTrays.length === 1 && getValues("tray_id") !== matchingBatchTrays[0].tray.id) {
      setValue("tray_id", matchingBatchTrays[0].tray.id);
    }
    // Only ever auto-select once, when exactly one tray from the incoming
    // Batch is eligible -- never re-run on every render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [matchingBatchTrays.length, initialTrayId]);
  useEffect(() => {
    if (frozenTray && getValues("tray_id") !== frozenTray.tray.id) {
      setValue("tray_id", frozenTray.tray.id);
    }
    // Sets the frozen Tray exactly once it resolves -- never re-runs for any
    // other reason, so it can't overwrite an operator's in-progress edit.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [frozenTray?.tray.id]);
  const selectedLevel = levels.find((lvl) => lvl.id === selectedLevelId) ?? null;
  const openSlots = selectedLevel?.mode === "legacy" ? selectedLevel.slots.filter((s) => !s.occupied) : [];

  if (initialTrayId && traysQuery.isSuccess && !frozenTray) {
    return (
      <div className="flex flex-col gap-4">
        <p className="rounded-md border border-wl-border-strong bg-wl-flag-bg px-3 py-2 text-sm text-wl-flag-fg">
          This Seed Tray is no longer awaiting Germination placement -- its state changed since the worklist last
          loaded. Return to the worklist to see its current status.
        </p>
        <Button type="button" variant="secondary" className="self-start" onClick={onCancel}>
          Back to worklist
        </Button>
      </div>
    );
  }

  // PILOT-UX-001 (CTO correction): a Sowing batch commonly has many eligible
  // trays -- the backend only ever moves one tray per command (confirmed:
  // no bulk placement command exists), so this swaps in a board that keeps
  // the Batch and destination selected once and fires fast sequential
  // single-tray moves, rather than forcing the full configure/review form
  // and Batch/Tray re-selection for every single tray.
  // PILOT-BLOCKER-010: once a run has actually started, the board stays
  // shown until that run is fully resolved or safely abandoned via
  // `guardedDone` -- never re-derived from the live, shrinking
  // `matchingBatchTrays.length` again (that was the unmount-mid-run bug).
  const showBulkBoard =
    Boolean(frozenRun) ||
    (!initialTrayId && Boolean(initialBatchId) && Boolean(onSubmitOne) && matchingBatchTrays.length > 1 && !forceSingleMode);
  if (showBulkBoard) {
    return (
      <BulkMoveBoard
        farmId={farmId}
        batchCode={frozenRun?.batchCode ?? matchingBatchTrays[0]?.batch_code ?? ""}
        trays={matchingBatchTrays}
        frozenRun={frozenRun}
        hasUnknownEntry={hasUnknownRunEntry}
        isRunningAny={isRunningAny}
        onSubmitEntry={(trayId, destination) => { void submitRunEntry(trayId, destination); }}
        onRunAll={(destination) => { void runAll(destination); }}
        onSwitchToSingle={guardedSwitchToSingle}
        onCancel={guardedDone}
        onSetUpTrolley={onSetUpTrolley}
      />
    );
  }

  async function goToReview() {
    const valid = await trigger();
    if (valid) setStep("review");
  }

  function submitReview() {
    onSubmit(buildPlaceTrayPayload(getValues(), clientCommandId));
  }

  function handleLevelChange(levelId: string) {
    setSelectedLevelId(levelId);
    const level = levels.find((lvl) => lvl.id === levelId);
    // A `direct` Level is itself the terminal target -- submit its own id
    // immediately. A `legacy` Level still needs a Slot choice below, so its
    // target starts blank; an `invalid`/full Level is never selectable (its
    // `<option>` is disabled), so this branch is unreachable for it.
    setValue("asset_position_id", level?.mode === "direct" ? level.id : "");
  }

  if (step === "review") {
    const values = getValues();
    const tray = eligibleTrays.find((t) => t.tray.id === values.tray_id);
    const trolley = trolleys.find((t) => t.id === values.trolley_id);
    const slot = selectedLevel?.mode === "legacy" ? openSlots.find((s) => s.id === values.asset_position_id) : null;
    return (
      <div className="flex flex-col gap-4">
        <div className="flex flex-col gap-4 rounded-xl border border-wl-border bg-wl-surface-raised p-4">
          <h2 className="font-serif text-base font-semibold text-wl-text">Review before moving</h2>
          <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm sm:grid-cols-3">
            <div>
              <dt className="text-wl-text-secondary">Batch</dt>
              <dd className="font-medium text-wl-text">{tray?.batch_code}</dd>
            </div>
            <div>
              <dt className="text-wl-text-secondary">Seed Tray</dt>
              <dd className="font-medium text-wl-text">{tray?.tray.code}</dd>
            </div>
            <div>
              <dt className="text-wl-text-secondary">Seeds sown</dt>
              <dd className="font-medium text-wl-text">{tray?.seeds_sown.toLocaleString()}</dd>
            </div>
            <div>
              <dt className="text-wl-text-secondary">Trolley</dt>
              <dd className="font-medium text-wl-text">{trolley?.code}</dd>
            </div>
            <div>
              <dt className="text-wl-text-secondary">Germination Chamber</dt>
              <dd className="font-medium text-wl-text">{trolley?.chamber.code}</dd>
            </div>
            <div>
              <dt className="text-wl-text-secondary">Level</dt>
              <dd className="font-medium text-wl-text">{selectedLevel?.code}</dd>
            </div>
            {selectedLevel?.mode === "legacy" && (
              <div>
                <dt className="text-wl-text-secondary">Slot</dt>
                <dd className="font-medium text-wl-text">{slot?.code}</dd>
              </div>
            )}
            <div>
              <dt className="text-wl-text-secondary">Occurred at</dt>
              <dd className="font-medium text-wl-text">
                {values.effective_date} {values.effective_time_of_day}
              </dd>
            </div>
          </dl>
        </div>
        {serverError && <p role="alert" className={errorClass}>{serverError}</p>}
        <div className="flex gap-3">
          <Button type="button" variant="secondary" onClick={() => setStep("configure")} disabled={isSubmitting}>
            Back
          </Button>
          <Button type="button" variant="primary" onClick={submitReview} disabled={isSubmitting}>
            {isSubmitting ? "Moving…" : "Move to Germination"}
          </Button>
        </div>
      </div>
    );
  }

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        goToReview();
      }}
      className="flex flex-col gap-6"
    >
      {initialBatchId && !frozenTray && matchingBatchTrays.length > 0 && (
        <p className="rounded-md border border-wl-border-strong bg-wl-brand-subtle px-3 py-2 text-xs text-wl-brand">
          Continuing from Sowing — {matchingBatchTrays.length === 1 ? "this Batch's Seed Tray is preselected" : "this Batch's Seed Trays are listed first"} below.
        </p>
      )}
      {frozenTray && (
        <p className="rounded-md border border-wl-border-strong bg-wl-brand-subtle px-3 py-2 text-xs text-wl-brand">
          From the Germination worklist — Batch {frozenTray.batch_code}, Seed Tray {frozenTray.tray.code}.
        </p>
      )}
      <fieldset className="flex flex-col gap-4 rounded-xl border border-wl-border bg-wl-surface-raised p-4">
        <legend className="px-1 text-sm font-semibold text-wl-text">Seed Tray</legend>
        {frozenTray ? (
          <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm sm:grid-cols-3">
            <div>
              <dt className="text-wl-text-secondary">Batch</dt>
              <dd className="font-medium text-wl-text">{frozenTray.batch_code}</dd>
            </div>
            <div>
              <dt className="text-wl-text-secondary">Seed Tray</dt>
              <dd className="font-medium text-wl-text">{frozenTray.tray.code}</dd>
            </div>
            <div>
              <dt className="text-wl-text-secondary">Seeds sown</dt>
              <dd className="font-medium text-wl-text">{frozenTray.seeds_sown.toLocaleString()}</dd>
            </div>
          </dl>
        ) : traysQuery.isSuccess && eligibleTrays.length === 0 ? (
          <p className="text-sm text-wl-text-secondary">No Seed Trays are awaiting Germination placement.</p>
        ) : (
          <Field label="Seed Tray" error={errors.tray_id?.message}>
            <select {...register("tray_id")} className={inputClass}>
              <option value="">Select a Seed Tray…</option>
              {orderedEligibleTrays.map((t) => (
                <option key={t.tray.id} value={t.tray.id}>
                  {t.batch_code} — {t.tray.code} ({t.seeds_sown} seeds)
                </option>
              ))}
            </select>
          </Field>
        )}
      </fieldset>

      <fieldset className="flex flex-col gap-4 rounded-xl border border-wl-border bg-wl-surface-raised p-4">
        <legend className="px-1 text-sm font-semibold text-wl-text">Trolley / Level</legend>
        {trolleysQuery.isSuccess && trolleys.length === 0 ? (
          <EmptyState
            title="No Germination Trolley placed"
            description="No Trolleys are currently placed in a Germination Chamber. Place a Trolley before moving a Seed Tray onto it."
            action={
              onSetUpTrolley ? (
                <Button type="button" variant="secondary" onClick={onSetUpTrolley}>
                  Place Trolley
                </Button>
              ) : undefined
            }
          />
        ) : (
          <>
            <Field label="Trolley" error={errors.trolley_id?.message}>
              <select
                {...register("trolley_id")}
                className={inputClass}
                onChange={(e) => {
                  setValue("trolley_id", e.target.value);
                  setSelectedTrolleyId(e.target.value);
                  setSelectedLevelId("");
                  setValue("asset_position_id", "");
                }}
              >
                <option value="">Select a Trolley…</option>
                {trolleys.map((trolley) => (
                  <option key={trolley.id} value={trolley.id}>
                    {trolley.code} — {trolley.chamber.code} ({trolley.available_capacity} of{" "}
                    {trolley.total_capacity} free)
                  </option>
                ))}
              </select>
            </Field>
            {selectedTrolleyId && (
              <Field label="Level" error={errors.asset_position_id?.message}>
                <select
                  value={selectedLevelId}
                  onChange={(e) => handleLevelChange(e.target.value)}
                  className={inputClass}
                >
                  <option value="">Select a Level…</option>
                  {levels.map((level) => {
                    const isFull = level.mode !== "invalid" && (level.available_capacity ?? 0) <= 0;
                    const disabled = level.mode === "invalid" || isFull;
                    const suffix =
                      level.mode === "invalid"
                        ? " (not configured)"
                        : isFull
                          ? " (full)"
                          : level.mode === "direct"
                            ? ` (${level.available_capacity} of ${level.capacity} free)`
                            : ` (${level.available_capacity} slot${level.available_capacity === 1 ? "" : "s"} free)`;
                    return (
                      <option key={level.id} value={level.id} disabled={disabled}>
                        {level.code}
                        {suffix}
                      </option>
                    );
                  })}
                </select>
              </Field>
            )}
            {selectedLevel?.mode === "legacy" && (
              <Field label="Slot" error={errors.asset_position_id?.message}>
                <select {...register("asset_position_id")} className={inputClass}>
                  <option value="">Select a Slot…</option>
                  {openSlots.map((slot) => (
                    <option key={slot.id} value={slot.id}>
                      {slot.code}
                    </option>
                  ))}
                </select>
              </Field>
            )}
          </>
        )}
      </fieldset>

      <fieldset className="grid grid-cols-1 gap-4 rounded-xl border border-wl-border bg-wl-surface-raised p-4 sm:grid-cols-2">
        <legend className="px-1 text-sm font-semibold text-wl-text">Placement date/time</legend>
        <Field label="Date" error={errors.effective_date?.message}>
          <input type="date" {...register("effective_date")} className={inputClass} />
        </Field>
        <Field label="Time" error={errors.effective_time_of_day?.message}>
          <input type="time" {...register("effective_time_of_day")} className={inputClass} />
        </Field>
      </fieldset>

      <fieldset className="flex flex-col gap-4 rounded-xl border border-wl-border bg-wl-surface-raised p-4">
        <legend className="px-1 text-sm font-semibold text-wl-text">Reason (optional)</legend>
        <textarea {...register("reason")} className={`${inputClass} min-h-20`} rows={2} />
      </fieldset>

      <div className="flex gap-3">
        <Button type="button" variant="secondary" onClick={onCancel}>
          Cancel
        </Button>
        <Button type="submit" variant="primary">
          Review
        </Button>
      </div>
    </form>
  );
}
