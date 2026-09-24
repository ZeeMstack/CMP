"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";

import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { LoadingSkeleton } from "@/components/LoadingSkeleton";
import { BoundedDataRegion } from "@/components/layout/BoundedDataRegion";
import { ContextStrip, ContextStripItem } from "@/components/layout/ContextStrip";
import { InspectorEmptyState, InspectorShell } from "@/components/layout/InspectorShell";
import { QueueList, QueueRow } from "@/components/layout/QueueRow";
import { SplitWorkspace } from "@/components/layout/SplitWorkspace";
import { StickyActionBar } from "@/components/layout/StickyActionBar";
import { ViewTabs } from "@/components/layout/ViewTabs";
import { Button } from "@/components/ui/Button";
import {
  BlockerList,
  Fact,
  FactList,
  TimingField,
  WaterWorkspaceHeader,
  cardClass,
  commandErrorLine,
  entityLabel,
  inputClass,
  labelClass,
  labelTextClass,
  linkButtonClass,
  localInputToIso,
  stepLabelClass,
  type TimingMode,
} from "@/components/water/waterUi";
import type { NutrientMixCreate, NutrientMixRead } from "@/lib/api/client";
import { settleFrozenAttempt, useFrozenSubmission, useReportCommandLocked } from "@/lib/commands/frozenSubmission";
import { formatDateTimeWithZoneLabel } from "@/lib/format/datetime";
import { humanizeEnumCode } from "@/lib/format/humanize";
import { useViewState } from "@/lib/navigation/useViewState";
import {
  useFarm,
  useInventoryItems,
  useMixInputs,
  useMixesForFarm,
  useNutrientRecipeComponents,
  useNutrientRecipeVersion,
  useNutrientRecipeVersions,
  useNutrientRecipes,
  useRecordMix,
  useReservoirs,
  useUoms,
} from "@/lib/query/hooks";

const VIEWS = ["record", "recent"] as const;
type View = (typeof VIEWS)[number];

type InputRow = {
  key: string;
  component_label: string;
  inventory_item_id: string;
  actual_quantity: string;
  actual_quantity_uom_id: string;
  note: string;
};

function newInputRow(): InputRow {
  return {
    key: crypto.randomUUID(),
    component_label: "", inventory_item_id: "", actual_quantity: "", actual_quantity_uom_id: "", note: "",
  };
}

function isBlankRow(row: InputRow): boolean {
  return !row.component_label.trim() && !row.inventory_item_id && !row.actual_quantity.trim() && !row.actual_quantity_uom_id && !row.note.trim();
}

/** The exact frozen command: target, full wire payload (incl. id), and the
 * display labels Review/Receipt/Retry show -- never re-derived from live
 * form or query state while the attempt is unresolved. */
export type FrozenMix = {
  reservoirId: string;
  reservoirLabel: string;
  recipeLabel: string | null;
  uomCodes: Record<string, string>;
  itemLabels: Record<string, string>;
  payload: NutrientMixCreate;
};

/** Variance only when both values exist and the UOMs are literally the same
 * unit -- no conversion is ever invented. Exact decimal arithmetic. */
export function mixVolumeVariance(
  target: string | null | undefined, targetUom: string | null | undefined,
  actual: string | null | undefined, actualUom: string | null | undefined,
): string | null {
  if (!target || !actual || !targetUom || targetUom !== actualUom) return null;
  const places = Math.max((target.split(".")[1] ?? "").length, (actual.split(".")[1] ?? "").length);
  const scale = 10 ** places;
  const t = Math.round(Number(target) * scale);
  const a = Math.round(Number(actual) * scale);
  if (!Number.isFinite(t) || !Number.isFinite(a)) return null;
  const diff = (a - t) / scale;
  return `${diff > 0 ? "+" : diff < 0 ? "−" : "±"}${Math.abs(diff).toFixed(places)}`;
}

function volumeText(value: string | number | null | undefined, uomCode: string | undefined): string {
  if (value === null || value === undefined || value === "") return "Not recorded";
  return `${value}${uomCode ? ` ${uomCode}` : ""}`;
}

/** Record view: Configure -> Review -> Receipt. The frozen command lives
 * here; the page keeps this mounted across view changes. */
export function MixRecorder({ farmId, onLockedChange }: { farmId: string; onLockedChange: (locked: boolean) => void }) {
  const reservoirsQuery = useReservoirs(farmId);
  const recipesQuery = useNutrientRecipes();
  const uomsQuery = useUoms();
  const inventoryItemsQuery = useInventoryItems({ status: "active" });
  const recordMix = useRecordMix(farmId);
  const command = useFrozenSubmission<FrozenMix>();
  const locked = command.outcome !== "editing";
  useReportCommandLocked(command.outcome, onLockedChange);

  const [reservoirId, setReservoirId] = useState("");
  const [recipeId, setRecipeId] = useState("");
  const [recipeVersionId, setRecipeVersionId] = useState("");
  const [targetVolume, setTargetVolume] = useState("");
  const [targetUomId, setTargetUomId] = useState("");
  const [actualVolume, setActualVolume] = useState("");
  const [actualUomId, setActualUomId] = useState("");
  const [timingMode, setTimingMode] = useState<TimingMode>("now");
  const [customTime, setCustomTime] = useState("");
  const [notes, setNotes] = useState("");
  const [rows, setRows] = useState<InputRow[]>(() => [newInputRow()]);
  const [step, setStep] = useState<"configure" | "review">("configure");
  const [draft, setDraft] = useState<Omit<FrozenMix, "payload"> & { payload: Omit<NutrientMixCreate, "client_command_id"> } | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [receipt, setReceipt] = useState<{ mix: NutrientMixRead; frozen: FrozenMix } | null>(null);

  const versionsQuery = useNutrientRecipeVersions(recipeId || undefined);
  const componentsQuery = useNutrientRecipeComponents(recipeVersionId || undefined);
  const selectedVersion = (versionsQuery.data ?? []).find((v) => v.id === recipeVersionId);
  const reservoir = (reservoirsQuery.data ?? []).find((r) => r.id === reservoirId);
  const recipe = (recipesQuery.data ?? []).find((r) => r.id === recipeId);
  const uoms = uomsQuery.data ?? [];
  const volumeUoms = uoms.filter((u) => u.quantity_kind === "volume");
  const uomCode = (id: string | null | undefined) => (id ? uoms.find((u) => u.id === id)?.code : undefined);
  const items = inventoryItemsQuery.data ?? [];

  function updateRow(key: string, patch: Partial<InputRow>) {
    setRows((prev) => prev.map((r) => (r.key === key ? { ...r, ...patch } : r)));
  }

  function buildDraft() {
    setFormError(null);
    if (!reservoir) return setFormError("Choose a Reservoir / Tank first.");
    if (recipeId && !selectedVersion) return setFormError("Choose the Recipe Version, or clear the Recipe reference.");
    if (targetVolume.trim() && !targetUomId) return setFormError("Choose the Target Volume unit.");
    if (actualVolume.trim() && !actualUomId) return setFormError("Choose the Actual Volume unit.");
    const filled = rows.filter((r) => !isBlankRow(r));
    for (const [index, row] of filled.entries()) {
      if (!row.component_label.trim() || !row.actual_quantity.trim() || !row.actual_quantity_uom_id) {
        return setFormError(`Input row ${index + 1}: component, actual quantity, and unit are all required.`);
      }
      if (!(Number(row.actual_quantity) > 0)) return setFormError(`Input row ${index + 1}: actual quantity must be greater than zero.`);
    }
    if (filled.length === 0) return setFormError("Record at least one actual input. Recipe targets are never copied in.");
    let effectiveAt: string | null = null;
    if (timingMode === "custom") {
      effectiveAt = localInputToIso(customTime);
      if (!effectiveAt) return setFormError("Enter the custom time, or choose Now (server time).");
      if (new Date(effectiveAt).getTime() > Date.now()) return setFormError("The custom time cannot be in the future.");
    }
    const recipeLabel = recipe && selectedVersion ? `${entityLabel(recipe)} · v${selectedVersion.version_number}` : null;
    const uomCodes: Record<string, string> = Object.fromEntries(uoms.map((u) => [u.id, u.code]));
    const itemLabels: Record<string, string> = Object.fromEntries(items.map((i) => [i.id, entityLabel(i) ?? i.name]));
    setDraft({
      reservoirId: reservoir.id,
      reservoirLabel: entityLabel(reservoir) ?? "",
      recipeLabel,
      uomCodes,
      itemLabels,
      payload: {
        nutrient_recipe_version_id: selectedVersion?.id ?? null,
        effective_at: effectiveAt,
        target_volume: targetVolume.trim() || null,
        target_volume_uom_id: targetVolume.trim() ? targetUomId : null,
        actual_volume: actualVolume.trim() || null,
        actual_volume_uom_id: actualVolume.trim() ? actualUomId : null,
        notes: notes.trim() || null,
        inputs: filled.map((row, index) => ({
          component_label: row.component_label.trim(),
          inventory_item_id: row.inventory_item_id || null,
          actual_quantity: row.actual_quantity.trim(),
          actual_quantity_uom_id: row.actual_quantity_uom_id,
          sequence_number: index + 1,
          note: row.note.trim() || null,
        })),
      },
    });
    setStep("review");
  }

  function send(frozen: FrozenMix) {
    const result = recordMix.mutateAsync({ reservoirId: frozen.reservoirId, payload: frozen.payload });
    result.then((mix) => setReceipt({ mix, frozen }), () => undefined);
    settleFrozenAttempt(command, result);
  }

  function recordCommand() {
    if (command.outcome === "uncertain") {
      const frozen = command.retry();
      if (frozen) send(frozen);
      return;
    }
    if (!draft) return;
    // Frozen HERE, on the first actual submission -- never on Review.
    send(command.submit((clientCommandId) => ({ ...draft, payload: { ...draft.payload, client_command_id: clientCommandId } })));
  }

  function recordAnother() {
    setReceipt(null);
    setDraft(null);
    setStep("configure");
    setRows([newInputRow()]);
    setActualVolume("");
    setTargetVolume("");
    setNotes("");
    setTimingMode("now");
    setCustomTime("");
  }

  if (receipt) return <MixReceipt farmId={farmId} receipt={receipt} onRecordAnother={recordAnother} />;

  // Review renders the FROZEN snapshot while an attempt exists, else the draft.
  const shown = command.frozenPayload ?? (draft ? { ...draft, payload: { ...draft.payload, client_command_id: "" } } : null);
  if ((step === "review" || locked) && shown) {
    const p = shown.payload;
    const variance = mixVolumeVariance(
      p.target_volume != null ? String(p.target_volume) : null, p.target_volume_uom_id,
      p.actual_volume != null ? String(p.actual_volume) : null, p.actual_volume_uom_id,
    );
    return (
      <div>
        <p className={stepLabelClass}>Step 2 of 2 · Review</p>
        <SplitWorkspace
          main={
            <section aria-label="Review mix" className={`${cardClass} flex flex-col gap-3`}>
              <h2 className="font-serif text-base font-semibold text-wl-text">Review before recording</h2>
              <FactList>
                <Fact label="Reservoir / Tank">{shown.reservoirLabel}</Fact>
                <Fact label="Recipe reference (guidance only)">{shown.recipeLabel ?? "No recipe reference"}</Fact>
                <Fact label="Target volume">{volumeText(p.target_volume, shown.uomCodes[p.target_volume_uom_id ?? ""])}</Fact>
                <Fact label="Actual volume">{volumeText(p.actual_volume, shown.uomCodes[p.actual_volume_uom_id ?? ""])}</Fact>
                <Fact label="Effective time">
                  {p.effective_at ? formatDateTimeWithZoneLabel(p.effective_at) : "Now (server time)"}
                </Fact>
                <Fact label="Notes">{p.notes ?? "—"}</Fact>
              </FactList>
              {variance && <p className="text-xs text-wl-text-secondary">Actual vs target: {variance} {shown.uomCodes[p.actual_volume_uom_id ?? ""]}</p>}
              <h3 className="text-sm font-semibold text-wl-text">Actual inputs ({p.inputs.length}, in this order)</h3>
              <ol aria-label="Actual inputs" className="divide-y divide-wl-border rounded-lg border border-wl-border">
                {p.inputs.map((input) => (
                  <li key={input.sequence_number} className="flex flex-wrap justify-between gap-2 px-3 py-2 text-sm">
                    <span className="font-medium text-wl-text">
                      {input.sequence_number}. {input.component_label}: {input.actual_quantity} {shown.uomCodes[input.actual_quantity_uom_id]}
                    </span>
                    <span className="text-xs text-wl-text-secondary">
                      {input.inventory_item_id ? `Store item: ${shown.itemLabels[input.inventory_item_id] ?? "label unavailable"}` : "Not linked to Store"}
                      {input.note ? ` · ${input.note}` : ""}
                    </span>
                  </li>
                ))}
              </ol>
              <p className="text-xs text-wl-text-tertiary">Recording these inputs does not decrement Store inventory.</p>
            </section>
          }
          rail={
            <section aria-label="Record mix" className={`${cardClass} flex flex-col gap-3`}>
              <p className="text-sm text-wl-text">One Mix with {p.inputs.length} actual input(s).</p>
              <StickyActionBar blockers={<BlockerList lines={[commandErrorLine(command.error, command.outcome === "uncertain")]} />}>
                <div className="flex gap-2">
                  <Button variant="secondary" className="min-h-11" onClick={() => setStep("configure")} disabled={locked}>
                    Back to edit
                  </Button>
                  <Button variant="primary" className="min-h-11 flex-1" onClick={recordCommand} disabled={command.outcome === "submitting"}>
                    {command.outcome === "submitting" ? "Recording…" : command.outcome === "uncertain" ? "Retry" : "Record mix"}
                  </Button>
                </div>
              </StickyActionBar>
            </section>
          }
        />
      </div>
    );
  }

  const targetCode = uomCode(targetUomId);
  const actualCode = uomCode(actualUomId);
  const variance = mixVolumeVariance(targetVolume.trim(), targetUomId, actualVolume.trim(), actualUomId);
  const filledCount = rows.filter((r) => !isBlankRow(r)).length;

  return (
    <div>
      <p className={stepLabelClass}>Step 1 of 2 · Configure</p>
      <SplitWorkspace
        main={
          <div className="flex min-w-0 flex-col gap-3">
            <ContextStrip>
              <ContextStripItem minWidth="14rem">
                <label className={labelClass}>
                  <span className={labelTextClass}>Reservoir / Tank</span>
                  <select className={inputClass} value={reservoirId} onChange={(e) => setReservoirId(e.target.value)}>
                    <option value="">Select a Reservoir / Tank…</option>
                    {(reservoirsQuery.data ?? []).map((r) => (
                      <option key={r.id} value={r.id}>{entityLabel(r)} ({humanizeEnumCode(r.reservoir_type)})</option>
                    ))}
                  </select>
                </label>
              </ContextStripItem>
              <ContextStripItem minWidth="12rem">
                <label className={labelClass}>
                  <span className={labelTextClass}>Recipe (optional, guidance only)</span>
                  <select
                    className={inputClass}
                    value={recipeId}
                    onChange={(e) => { setRecipeId(e.target.value); setRecipeVersionId(""); }}
                  >
                    <option value="">No recipe reference</option>
                    {(recipesQuery.data ?? []).map((r) => (
                      <option key={r.id} value={r.id}>{entityLabel(r)}</option>
                    ))}
                  </select>
                </label>
              </ContextStripItem>
              {recipeId && (
                <ContextStripItem minWidth="10rem">
                  <label className={labelClass}>
                    <span className={labelTextClass}>Recipe Version</span>
                    <select className={inputClass} value={recipeVersionId} onChange={(e) => setRecipeVersionId(e.target.value)}>
                      <option value="">Select a version…</option>
                      {(versionsQuery.data ?? []).map((v) => (
                        <option key={v.id} value={v.id}>v{v.version_number} — {humanizeEnumCode(v.state)}</option>
                      ))}
                    </select>
                  </label>
                </ContextStripItem>
              )}
            </ContextStrip>
            {reservoirsQuery.isError && <ErrorState error={reservoirsQuery.error} onRetry={() => reservoirsQuery.refetch()} />}

            {selectedVersion && (
              <section
                aria-label="Recipe target guidance"
                className="rounded-lg border border-dashed border-wl-border-strong bg-wl-surface-sunken p-3 text-xs text-wl-text-secondary"
              >
                <p className="font-semibold text-wl-text">Recipe target — guidance only, never copied into the actual inputs below</p>
                <p>Target EC: {selectedVersion.target_ec ?? "not set"} · Target pH: {selectedVersion.target_ph ?? "not set"}</p>
                {componentsQuery.isError ? (
                  <p>Target components unavailable.</p>
                ) : (componentsQuery.data ?? []).length > 0 ? (
                  <ul className="mt-1 grid grid-cols-1 gap-x-4 sm:grid-cols-2">
                    {(componentsQuery.data ?? []).map((c) => (
                      <li key={c.id}>
                        {c.component_label}: target {c.target_quantity} {uomCode(c.target_quantity_uom_id) ?? ""}
                      </li>
                    ))}
                  </ul>
                ) : null}
              </section>
            )}

            <div className={`${cardClass} grid grid-cols-2 gap-3 p-3 md:grid-cols-4`}>
              <label className={labelClass}>
                <span className={labelTextClass}>Target volume</span>
                <input className={inputClass} inputMode="decimal" value={targetVolume} onChange={(e) => setTargetVolume(e.target.value)} placeholder="Optional" />
              </label>
              <label className={labelClass}>
                <span className={labelTextClass}>Target unit</span>
                <select className={inputClass} value={targetUomId} onChange={(e) => setTargetUomId(e.target.value)}>
                  <option value="">Unit…</option>
                  {volumeUoms.map((u) => <option key={u.id} value={u.id}>{u.code}</option>)}
                </select>
              </label>
              <label className={labelClass}>
                <span className={labelTextClass}>Actual volume</span>
                <input className={inputClass} inputMode="decimal" value={actualVolume} onChange={(e) => setActualVolume(e.target.value)} placeholder="Operator-entered" />
              </label>
              <label className={labelClass}>
                <span className={labelTextClass}>Actual unit</span>
                <select className={inputClass} value={actualUomId} onChange={(e) => setActualUomId(e.target.value)}>
                  <option value="">Unit…</option>
                  {volumeUoms.map((u) => <option key={u.id} value={u.id}>{u.code}</option>)}
                </select>
              </label>
            </div>

            <BoundedDataRegion
              label="Actual inputs"
              heading={
                <div className="flex items-center justify-between gap-2">
                  <span className="text-xs font-semibold text-wl-text">Actual inputs (operator-entered, in order)</span>
                  <button
                    type="button"
                    className="min-h-11 rounded-md px-2 text-xs font-medium text-wl-brand hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-wl-focus"
                    onClick={() => setRows((r) => [...r, newInputRow()])}
                  >
                    + Add input row
                  </button>
                </div>
              }
              footer={
                <span className="text-xs text-wl-text-secondary">
                  {filledCount} input(s) · Recording a Mix Input does not decrement Store inventory.
                </span>
              }
            >
              <ol className="divide-y divide-wl-border">
                {rows.map((row, index) => (
                  <li key={row.key} className="grid grid-cols-2 items-end gap-2 px-3 py-2 md:grid-cols-[2rem_1.4fr_1.4fr_0.8fr_0.8fr_1.2fr_auto]">
                    <span className="self-center text-xs font-semibold text-wl-text-secondary" aria-hidden="true">{index + 1}</span>
                    <label className={`${labelClass} col-span-2 md:col-span-1`}>
                      <span className="sr-only">Input {index + 1} component</span>
                      <input className={inputClass} placeholder="Component, e.g. Stock A" value={row.component_label} onChange={(e) => updateRow(row.key, { component_label: e.target.value })} />
                    </label>
                    <label className={`${labelClass} col-span-2 md:col-span-1`}>
                      <span className="sr-only">Input {index + 1} Store item</span>
                      <select className={inputClass} value={row.inventory_item_id} onChange={(e) => updateRow(row.key, { inventory_item_id: e.target.value })}>
                        <option value="">Not linked to Store</option>
                        {items.map((item) => <option key={item.id} value={item.id}>{entityLabel(item)}</option>)}
                      </select>
                    </label>
                    <label className={labelClass}>
                      <span className="sr-only">Input {index + 1} actual quantity</span>
                      <input className={inputClass} inputMode="decimal" placeholder="Qty" value={row.actual_quantity} onChange={(e) => updateRow(row.key, { actual_quantity: e.target.value })} />
                    </label>
                    <label className={labelClass}>
                      <span className="sr-only">Input {index + 1} unit</span>
                      <select className={inputClass} value={row.actual_quantity_uom_id} onChange={(e) => updateRow(row.key, { actual_quantity_uom_id: e.target.value })}>
                        <option value="">Unit…</option>
                        {uoms.map((u) => <option key={u.id} value={u.id}>{u.code}</option>)}
                      </select>
                    </label>
                    <label className={labelClass}>
                      <span className="sr-only">Input {index + 1} note</span>
                      <input className={inputClass} placeholder="Note (optional)" value={row.note} onChange={(e) => updateRow(row.key, { note: e.target.value })} />
                    </label>
                    <button
                      type="button"
                      aria-label={`Remove input ${index + 1}`}
                      disabled={rows.length === 1}
                      onClick={() => setRows((r) => r.filter((x) => x.key !== row.key))}
                      className="min-h-11 min-w-11 rounded-md text-wl-text-secondary hover:bg-wl-surface-hover disabled:opacity-40 focus-visible:outline focus-visible:outline-2 focus-visible:outline-wl-focus"
                    >
                      ×
                    </button>
                  </li>
                ))}
              </ol>
            </BoundedDataRegion>

            <details className={`${cardClass} p-3`}>
              <summary className="min-h-11 cursor-pointer content-center text-sm font-medium text-wl-text">
                Optional details — effective time ({timingMode === "now" ? "Now, server time" : "custom"}) and notes
              </summary>
              <div className="mt-2 grid grid-cols-1 gap-3 md:grid-cols-2">
                <TimingField
                  legend="Effective time"
                  mode={timingMode}
                  custom={customTime}
                  onModeChange={setTimingMode}
                  onCustomChange={setCustomTime}
                />
                <label className={labelClass}>
                  <span className={labelTextClass}>Notes (optional)</span>
                  <textarea className={`${inputClass} min-h-16 py-2`} value={notes} onChange={(e) => setNotes(e.target.value)} />
                </label>
              </div>
            </details>
          </div>
        }
        rail={
          <section aria-label="Target versus actual" className={`${cardClass} flex flex-col gap-3`}>
            <h2 className="text-sm font-semibold text-wl-text">Target vs actual</h2>
            <FactList>
              <Fact label="Target volume">{volumeText(targetVolume.trim(), targetCode)}</Fact>
              <Fact label="Actual volume">{volumeText(actualVolume.trim(), actualCode)}</Fact>
            </FactList>
            <p className="text-xs text-wl-text-secondary">
              {variance
                ? `Variance: ${variance} ${actualCode}`
                : targetVolume.trim() && actualVolume.trim() && targetUomId !== actualUomId
                  ? "Different units — no variance is calculated (no conversion is assumed)."
                  : "Variance shows when both volumes use the same unit."}
            </p>
            <p className="text-sm text-wl-text">{filledCount} actual input(s)</p>
            <StickyActionBar blockers={<BlockerList lines={[formError]} />}>
              <Button variant="primary" className="min-h-11 w-full" onClick={buildDraft}>
                Review mix
              </Button>
            </StickyActionBar>
          </section>
        }
      />
    </div>
  );
}

function MixReceipt({
  farmId, receipt, onRecordAnother,
}: {
  farmId: string;
  receipt: { mix: NutrientMixRead; frozen: FrozenMix };
  onRecordAnother: () => void;
}) {
  const { mix, frozen } = receipt;
  const inputsQuery = useMixInputs(mix.id);
  const codes = frozen.uomCodes;
  return (
    <section aria-label="Mix receipt" className={`${cardClass} flex flex-col gap-3`}>
      <p role="status" className="text-sm font-semibold text-wl-grow-fg">Mix recorded — confirmed by the server.</p>
      <FactList>
        <Fact label="Mix ID"><span className="font-mono text-xs">{mix.id}</span></Fact>
        <Fact label="Reservoir / Tank">{frozen.reservoirLabel}</Fact>
        <Fact label="Effective time (server)">{formatDateTimeWithZoneLabel(mix.effective_at)}</Fact>
        <Fact label="Recipe reference">{mix.nutrient_recipe_version_id ? frozen.recipeLabel ?? "Recipe-based" : "None"}</Fact>
        <Fact label="Target volume">{volumeText(mix.target_volume, codes[frozen.payload.target_volume_uom_id ?? ""])}</Fact>
        <Fact label="Actual volume">{volumeText(mix.actual_volume, codes[frozen.payload.actual_volume_uom_id ?? ""])}</Fact>
      </FactList>
      <h3 className="text-sm font-semibold text-wl-text">Recorded actual inputs</h3>
      {inputsQuery.isLoading ? (
        <LoadingSkeleton rows={2} label="Loading recorded inputs" />
      ) : inputsQuery.isError ? (
        <p className="text-xs text-wl-text-secondary">Recorded inputs could not be loaded — the Mix itself is confirmed.</p>
      ) : (
        <ol className="divide-y divide-wl-border rounded-lg border border-wl-border">
          {(inputsQuery.data ?? []).map((input) => (
            <li key={input.id} className="px-3 py-2 text-sm">
              {input.sequence_number ?? "—"}. {input.component_label}: {input.actual_quantity} {codes[input.actual_quantity_uom_id] ?? ""}
              {input.note ? <span className="text-xs text-wl-text-secondary"> · {input.note}</span> : null}
            </li>
          ))}
        </ol>
      )}
      <div className="flex flex-wrap gap-2">
        <Link href={`/farms/${farmId}/water/measurements`} className={linkButtonClass}>Record a measurement</Link>
        <Link href={`/farms/${farmId}/water/delivery`} className={linkButtonClass}>Record a delivery</Link>
        <Button variant="primary" className="min-h-11" onClick={onRecordAnother}>Record another mix</Button>
      </div>
    </section>
  );
}

function RecentMixes({ farmId }: { farmId: string }) {
  const mixesQuery = useMixesForFarm(farmId);
  const reservoirsQuery = useReservoirs(farmId);
  const { selected, setSelected } = useViewState<View>({ views: VIEWS, defaultView: "record" });
  const reservoirById = new Map((reservoirsQuery.data ?? []).map((r) => [r.id, r]));
  const rows = [...(mixesQuery.data ?? [])].sort((a, b) => new Date(b.effective_at).getTime() - new Date(a.effective_at).getTime());
  const selectedMix = rows.find((m) => m.id === selected);

  let main;
  if (mixesQuery.isLoading && !mixesQuery.data) main = <LoadingSkeleton rows={6} label="Loading mixes" />;
  else if (mixesQuery.isError && !mixesQuery.data) main = <ErrorState error={mixesQuery.error} onRetry={() => mixesQuery.refetch()} />;
  else if (rows.length === 0) main = <EmptyState title="No mixes recorded yet for this Farm" />;
  else {
    main = (
      <BoundedDataRegion label="Recent mixes" footer={<span className="text-xs text-wl-text-secondary">{rows.length} mix(es), newest first</span>}>
        <QueueList label="Recent mixes">
          {rows.map((m) => (
            <QueueRow
              key={m.id}
              isSelected={m.id === selected}
              onSelect={() => setSelected(m.id)}
              title={entityLabel(reservoirById.get(m.reservoir_id)) ?? "Reservoir label unavailable"}
              context={`${m.nutrient_recipe_version_id ? "Recipe-based" : "No recipe reference"} · Target ${m.target_volume ?? "—"} · Actual ${m.actual_volume ?? "—"}`}
              meta={formatDateTimeWithZoneLabel(m.effective_at)}
            />
          ))}
        </QueueList>
      </BoundedDataRegion>
    );
  }
  return (
    <SplitWorkspace
      main={main}
      rail={selectedMix ? <MixDetail mix={selectedMix} reservoirLabel={entityLabel(reservoirById.get(selectedMix.reservoir_id))} onClose={() => setSelected(null)} /> : <InspectorEmptyState label="Select a mix to see its recorded inputs." />}
    />
  );
}

function MixDetail({ mix, reservoirLabel, onClose }: { mix: NutrientMixRead; reservoirLabel: string | null; onClose: () => void }) {
  const inputsQuery = useMixInputs(mix.id);
  const versionQuery = useNutrientRecipeVersion(mix.nutrient_recipe_version_id ?? undefined);
  const recipesQuery = useNutrientRecipes();
  const uomsQuery = useUoms();
  const codes = new Map((uomsQuery.data ?? []).map((u) => [u.id, u.code]));
  const recipe = (recipesQuery.data ?? []).find((r) => r.id === versionQuery.data?.nutrient_recipe_id);
  const recipeLabel = !mix.nutrient_recipe_version_id
    ? "None"
    : versionQuery.data
      ? `${entityLabel(recipe) ?? "Recipe"} · v${versionQuery.data.version_number}`
      : versionQuery.isError
        ? "Recipe label unavailable"
        : "Loading…";
  return (
    <InspectorShell title={reservoirLabel ?? "Reservoir label unavailable"} subtitle={formatDateTimeWithZoneLabel(mix.effective_at)} onClose={onClose}>
      <FactList>
        <Fact label="Recipe reference">{recipeLabel}</Fact>
        <Fact label="Target / actual volume">
          {mix.target_volume ?? "—"} / {mix.actual_volume ?? "—"}
          <span className="block text-xs text-wl-text-tertiary">Volume units are not included in this read.</span>
        </Fact>
        <Fact label="Notes">{mix.notes ?? "—"}</Fact>
        <Fact label="Mix ID"><span className="font-mono text-xs">{mix.id}</span></Fact>
      </FactList>
      <h3 className="text-sm font-semibold text-wl-text">Recorded actual inputs</h3>
      {inputsQuery.isLoading ? (
        <LoadingSkeleton rows={2} label="Loading inputs" />
      ) : inputsQuery.isError ? (
        <ErrorState error={inputsQuery.error} onRetry={() => inputsQuery.refetch()} />
      ) : (
        <ol className="divide-y divide-wl-border rounded-lg border border-wl-border">
          {(inputsQuery.data ?? []).map((input) => (
            <li key={input.id} className="px-3 py-2 text-sm">
              {input.sequence_number ?? "—"}. {input.component_label}: {input.actual_quantity} {codes.get(input.actual_quantity_uom_id) ?? "(unit unavailable)"}
              {input.note ? <span className="text-xs text-wl-text-secondary"> · {input.note}</span> : null}
            </li>
          ))}
        </ol>
      )}
    </InspectorShell>
  );
}

/** UX-OPS-001D: URL-backed Record / Recent mixes views -- never the recent
 * table stacked under the command form. */
export default function WaterMixingPage() {
  const { farmId } = useParams<{ farmId: string }>();
  const { data: farm } = useFarm(farmId);
  const { view, setView } = useViewState<View>({ views: VIEWS, defaultView: "record" });
  const [locked, setLocked] = useState(false);

  return (
    <div>
      <WaterWorkspaceHeader
        farmId={farmId}
        title="Mixing"
        description={farm ? `Record what was actually mixed for ${farm.name}` : undefined}
        locked={locked}
      />
      <div className="mb-3">
        <ViewTabs
          items={[
            { value: "record", label: "Record" },
            { value: "recent", label: "Recent mixes" },
          ]}
          active={view}
          onChange={setView}
          disabled={locked}
        />
      </div>
      <div hidden={view !== "record"}>
        <MixRecorder farmId={farmId} onLockedChange={setLocked} />
      </div>
      {view === "recent" && <RecentMixes farmId={farmId} />}
    </div>
  );
}
