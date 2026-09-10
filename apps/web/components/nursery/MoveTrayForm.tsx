"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useEffect, useState } from "react";
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
  "min-h-11 w-full rounded-md border border-border-subtle bg-surface px-3 text-sm text-ink focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-600";
const labelClass = "block text-sm font-medium text-ink";
const errorClass = "text-xs text-red-700";

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

/** Progress/outcome of a "Move All" run -- a truthful record, not an
 * optimistic one: a mid-run failure is reported exactly where it stopped,
 * never presented as if earlier successful `place_tray` calls could be
 * rolled back (they can't -- each already committed independently). */
type BulkRunState =
  | { phase: "idle" }
  | { phase: "running"; total: number; completed: number; currentTrayCode: string }
  | { phase: "done"; succeeded: number; trolleyCode: string; levelCode: string }
  | { phase: "partial"; succeeded: number; remaining: number; failedTrayCode: string; failedReason: string };

/** PILOT-UX-001 (CTO correction): a Sowing batch commonly spans 5-50+ Seed
 * Trays. The backend's `place_tray` command (`PlaceTrayCreate`) accepts
 * exactly one `tray_id` per call -- confirmed no bulk/list-based placement
 * command exists anywhere in this domain (movements and transplant are
 * likewise single-entity). Redesigning that is out of scope here, so this
 * board keeps the Batch and destination (Trolley/Level) selected ONCE.
 * "Move All" orchestrates the SAME single-tray command sequentially with
 * its own idempotency key per call; a per-row "Move" stays available as a
 * manual/exception path. A follow-up candidate (reported, not built here):
 * a real bulk placement command if/when the backend adds one. */
function BulkMoveBoard({
  farmId, batchCode, trays, onSubmitOne, onSwitchToSingle, onCancel, onSetUpTrolley,
}: {
  farmId: string;
  batchCode: string;
  trays: GerminationTrayRead[];
  onSubmitOne: (payload: PlaceTrayCreate) => Promise<unknown>;
  onSwitchToSingle: () => void;
  onCancel: () => void;
  onSetUpTrolley?: () => void;
}) {
  const [trolleyId, setTrolleyId] = useState("");
  const [levelId, setLevelId] = useState("");
  const [reason, setReason] = useState("");
  const [showRowTable, setShowRowTable] = useState(false);
  const [rowStatus, setRowStatus] = useState<Record<string, "moving" | "error">>({});
  const [rowError, setRowError] = useState<Record<string, string>>({});
  const [bulkRun, setBulkRun] = useState<BulkRunState>({ phase: "idle" });

  const trolleysQuery = useAvailableTrolleys(farmId);
  const trolleys = trolleysQuery.data ?? [];
  const levelsQuery = useTrolleyLevels(farmId, trolleyId);
  const levels = levelsQuery.data ?? [];
  const selectedLevel = levels.find((l) => l.id === levelId) ?? null;
  const destinationReady = Boolean(trolleyId && levelId);
  const levelIsFull = selectedLevel !== null && (selectedLevel.available_capacity ?? 0) <= 0;
  const isRunning = bulkRun.phase === "running";
  // PILOT-UX-001 (CTO correction): use ONLY the already-fetched Level
  // capacity to rule out an obviously-impossible run before starting --
  // never a re-implementation of backend capacity logic, which remains
  // authoritative for every individual `place_tray` call regardless.
  const capacityInsufficient =
    selectedLevel !== null && selectedLevel.mode === "direct" && (selectedLevel.available_capacity ?? 0) < trays.length;

  async function moveTray(trayId: string) {
    if (!destinationReady) return;
    setRowStatus((s) => ({ ...s, [trayId]: "moving" }));
    setRowError((s) => {
      const next = { ...s };
      delete next[trayId];
      return next;
    });
    try {
      await onSubmitOne({
        client_command_id: crypto.randomUUID(),
        tray_id: trayId,
        trolley_id: trolleyId,
        asset_position_id: levelId,
        effective_time: new Date().toISOString(),
        reason: reason.trim() || null,
      });
      setRowStatus((s) => {
        const next = { ...s };
        delete next[trayId];
        return next;
      });
    } catch (err) {
      setRowStatus((s) => ({ ...s, [trayId]: "error" }));
      setRowError((s) => ({ ...s, [trayId]: err instanceof AppError ? err.message : "Move failed. Try again." }));
    }
  }

  /** PILOT-UX-001 (CTO correction): "Move All" -- frontend orchestration
   * over the SAME existing single-tray `place_tray` command, called
   * sequentially with its own idempotency key each time. No new backend
   * endpoint. Stops at the first failure and reports exactly how far it
   * got -- earlier successful calls already committed and are never
   * pretended to have rolled back. */
  async function moveAll() {
    if (!destinationReady || isRunning || capacityInsufficient) return;
    const targets = trays;
    const trolleyCode = trolleys.find((t) => t.id === trolleyId)?.code ?? "";
    const levelCode = selectedLevel?.code ?? "";
    for (let i = 0; i < targets.length; i += 1) {
      const t = targets[i];
      setBulkRun({ phase: "running", total: targets.length, completed: i, currentTrayCode: t.tray.code });
      try {
        // Deliberately sequential: each call must commit before the next
        // starts, so a mid-run failure stops cleanly at a known point.
        await onSubmitOne({
          client_command_id: crypto.randomUUID(),
          tray_id: t.tray.id,
          trolley_id: trolleyId,
          asset_position_id: levelId,
          effective_time: new Date().toISOString(),
          reason: reason.trim() || null,
        });
      } catch (err) {
        setBulkRun({
          phase: "partial",
          succeeded: i,
          remaining: targets.length - i,
          failedTrayCode: t.tray.code,
          failedReason: err instanceof AppError ? err.message : "Move failed.",
        });
        return;
      }
    }
    setBulkRun({ phase: "done", succeeded: targets.length, trolleyCode, levelCode });
  }

  return (
    <div className="flex flex-col gap-6">
      <p className="rounded-md border border-brand-200 bg-brand-50 px-3 py-2 text-xs text-brand-800">
        Continuing from Sowing — Batch {batchCode}, {trays.length} eligible Seed Tray{trays.length === 1 ? "" : "s"}.{" "}
        <button type="button" className="font-medium underline" onClick={onSwitchToSingle} disabled={isRunning}>
          Move a single Seed Tray instead
        </button>
      </p>

      <fieldset className="flex flex-col gap-4 rounded-xl border border-border-subtle bg-surface p-4">
        <legend className="px-1 text-sm font-semibold text-ink">Destination (applies to every move below)</legend>
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
                disabled={isRunning}
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
                  disabled={isRunning}
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

      <fieldset className="flex flex-col gap-4 rounded-xl border border-border-subtle bg-surface p-4">
        <legend className="px-1 text-sm font-semibold text-ink">Reason (optional, applies to every move below)</legend>
        <textarea
          className={`${inputClass} min-h-16`}
          rows={2}
          value={reason}
          disabled={isRunning}
          onChange={(e) => setReason(e.target.value)}
        />
      </fieldset>

      <div className="flex flex-col gap-3 rounded-lg border border-border-subtle bg-surface-subtle p-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <p className="text-sm font-medium text-ink">
              {trays.length} tray{trays.length === 1 ? "" : "s"} ready
            </p>
            {!destinationReady && (
              <p className="text-xs text-ink-muted">Choose a Trolley and Level to enable Move All.</p>
            )}
          </div>
          <div className="flex flex-wrap gap-2">
            <Button
              type="button"
              variant="primary"
              disabled={!destinationReady || isRunning || capacityInsufficient}
              onClick={moveAll}
            >
              {isRunning
                ? `Moving ${bulkRun.completed + 1} of ${bulkRun.total}…`
                : `Move All ${trays.length} Tray${trays.length === 1 ? "" : "s"}`}
            </Button>
            <Button type="button" variant="secondary" disabled={isRunning} onClick={() => setShowRowTable((v) => !v)}>
              {showRowTable ? "Hide trays" : "Show trays"}
            </Button>
          </div>
        </div>
        {capacityInsufficient && selectedLevel && (
          <p className="text-xs text-red-700">
            This Level only has {selectedLevel.available_capacity} of the {trays.length} needed free positions.
            Choose a Level with more capacity, or move trays individually below.
          </p>
        )}
      </div>

      {bulkRun.phase === "done" && (
        <div className="flex flex-col gap-2 rounded-lg border border-green-200 bg-green-50 p-3 text-sm text-green-900">
          <p>
            {bulkRun.succeeded} tray{bulkRun.succeeded === 1 ? "" : "s"} moved to Trolley {bulkRun.trolleyCode} /
            Level {bulkRun.levelCode}
          </p>
          <Button type="button" variant="secondary" className="self-start" onClick={onCancel}>
            Continue
          </Button>
        </div>
      )}

      {bulkRun.phase === "partial" && (
        <div className="flex flex-col gap-2 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-900">
          <p>
            {bulkRun.succeeded} tray{bulkRun.succeeded === 1 ? "" : "s"} moved successfully
          </p>
          <p>
            {bulkRun.remaining} tray{bulkRun.remaining === 1 ? "" : "s"} remain{bulkRun.remaining === 1 ? "s" : ""}
          </p>
          <p>
            Tray {bulkRun.failedTrayCode} could not be moved: {bulkRun.failedReason}
          </p>
          <Button
            type="button"
            variant="secondary"
            className="self-start"
            onClick={() => setBulkRun({ phase: "idle" })}
          >
            Continue Remaining
          </Button>
        </div>
      )}

      {showRowTable && (
        <div className="overflow-x-auto rounded-xl border border-border-subtle bg-surface">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-border-subtle bg-surface-subtle text-xs uppercase text-ink-muted">
              <tr>
                <th className="px-4 py-2 font-medium">Seed Tray</th>
                <th className="px-4 py-2 font-medium">Seeds sown</th>
                <th className="px-4 py-2 font-medium" />
              </tr>
            </thead>
            <tbody className="divide-y divide-border-subtle">
              {trays.map((t) => {
                const status = rowStatus[t.tray.id];
                return (
                  <tr key={t.tray.id}>
                    <td className="px-4 py-2 font-medium text-ink">{t.tray.code}</td>
                    <td className="px-4 py-2 text-ink-muted">{t.seeds_sown.toLocaleString()}</td>
                    <td className="px-4 py-2 text-right">
                      {rowError[t.tray.id] && <p className="mb-1 text-xs text-red-700">{rowError[t.tray.id]}</p>}
                      <Button
                        type="button"
                        variant={status === "error" ? "secondary" : "primary"}
                        disabled={!destinationReady || isRunning || status === "moving" || (status !== "error" && levelIsFull)}
                        onClick={() => moveTray(t.tray.id)}
                      >
                        {status === "moving" ? "Moving…" : status === "error" ? "Retry" : "Move"}
                      </Button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      <div>
        <Button type="button" variant="secondary" onClick={onCancel} disabled={isRunning}>
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
  farmId, onSubmit, onCancel, isSubmitting, serverError, initialBatchId, onSetUpTrolley, onSubmitOne,
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
}) {
  const [step, setStep] = useState<"configure" | "review">("configure");
  const [clientCommandId] = useState(() => crypto.randomUUID());
  const [selectedTrolleyId, setSelectedTrolleyId] = useState("");
  const [selectedLevelId, setSelectedLevelId] = useState("");
  const [forceSingleMode, setForceSingleMode] = useState(false);

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
  const trolleysQuery = useAvailableTrolleys(farmId);
  const trolleys = trolleysQuery.data ?? [];
  const levelsQuery = useTrolleyLevels(farmId, selectedTrolleyId);
  const levels = levelsQuery.data ?? [];

  useEffect(() => {
    if (matchingBatchTrays.length === 1 && getValues("tray_id") !== matchingBatchTrays[0].tray.id) {
      setValue("tray_id", matchingBatchTrays[0].tray.id);
    }
    // Only ever auto-select once, when exactly one tray from the incoming
    // Batch is eligible -- never re-run on every render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [matchingBatchTrays.length]);
  const selectedLevel = levels.find((lvl) => lvl.id === selectedLevelId) ?? null;
  const openSlots = selectedLevel?.mode === "legacy" ? selectedLevel.slots.filter((s) => !s.occupied) : [];

  // PILOT-UX-001 (CTO correction): a Sowing batch commonly has many eligible
  // trays -- the backend only ever moves one tray per command (confirmed:
  // no bulk placement command exists), so this swaps in a board that keeps
  // the Batch and destination selected once and fires fast sequential
  // single-tray moves, rather than forcing the full configure/review form
  // and Batch/Tray re-selection for every single tray.
  const showBulkBoard = Boolean(initialBatchId) && Boolean(onSubmitOne) && matchingBatchTrays.length > 1 && !forceSingleMode;
  if (showBulkBoard) {
    return (
      <BulkMoveBoard
        farmId={farmId}
        batchCode={matchingBatchTrays[0].batch_code}
        trays={matchingBatchTrays}
        onSubmitOne={onSubmitOne!}
        onSwitchToSingle={() => setForceSingleMode(true)}
        onCancel={onCancel}
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
        <div className="flex flex-col gap-4 rounded-xl border border-border-subtle bg-surface p-4">
          <h2 className="font-serif text-base font-semibold text-ink">Review before moving</h2>
          <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm sm:grid-cols-3">
            <div>
              <dt className="text-ink-muted">Batch</dt>
              <dd className="font-medium text-ink">{tray?.batch_code}</dd>
            </div>
            <div>
              <dt className="text-ink-muted">Seed Tray</dt>
              <dd className="font-medium text-ink">{tray?.tray.code}</dd>
            </div>
            <div>
              <dt className="text-ink-muted">Seeds sown</dt>
              <dd className="font-medium text-ink">{tray?.seeds_sown.toLocaleString()}</dd>
            </div>
            <div>
              <dt className="text-ink-muted">Trolley</dt>
              <dd className="font-medium text-ink">{trolley?.code}</dd>
            </div>
            <div>
              <dt className="text-ink-muted">Germination Chamber</dt>
              <dd className="font-medium text-ink">{trolley?.chamber.code}</dd>
            </div>
            <div>
              <dt className="text-ink-muted">Level</dt>
              <dd className="font-medium text-ink">{selectedLevel?.code}</dd>
            </div>
            {selectedLevel?.mode === "legacy" && (
              <div>
                <dt className="text-ink-muted">Slot</dt>
                <dd className="font-medium text-ink">{slot?.code}</dd>
              </div>
            )}
            <div>
              <dt className="text-ink-muted">Occurred at</dt>
              <dd className="font-medium text-ink">
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
      {initialBatchId && matchingBatchTrays.length > 0 && (
        <p className="rounded-md border border-brand-200 bg-brand-50 px-3 py-2 text-xs text-brand-800">
          Continuing from Sowing — {matchingBatchTrays.length === 1 ? "this Batch's Seed Tray is preselected" : "this Batch's Seed Trays are listed first"} below.
        </p>
      )}
      <fieldset className="flex flex-col gap-4 rounded-xl border border-border-subtle bg-surface p-4">
        <legend className="px-1 text-sm font-semibold text-ink">Seed Tray</legend>
        {traysQuery.isSuccess && eligibleTrays.length === 0 ? (
          <p className="text-sm text-ink-muted">No Seed Trays are awaiting Germination placement.</p>
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

      <fieldset className="flex flex-col gap-4 rounded-xl border border-border-subtle bg-surface p-4">
        <legend className="px-1 text-sm font-semibold text-ink">Trolley / Level</legend>
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

      <fieldset className="grid grid-cols-1 gap-4 rounded-xl border border-border-subtle bg-surface p-4 sm:grid-cols-2">
        <legend className="px-1 text-sm font-semibold text-ink">Placement date/time</legend>
        <Field label="Date" error={errors.effective_date?.message}>
          <input type="date" {...register("effective_date")} className={inputClass} />
        </Field>
        <Field label="Time" error={errors.effective_time_of_day?.message}>
          <input type="time" {...register("effective_time_of_day")} className={inputClass} />
        </Field>
      </fieldset>

      <fieldset className="flex flex-col gap-4 rounded-xl border border-border-subtle bg-surface p-4">
        <legend className="px-1 text-sm font-semibold text-ink">Reason (optional)</legend>
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
