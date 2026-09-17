"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";

import { Breadcrumbs } from "@/components/Breadcrumbs";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { LoadingSkeleton } from "@/components/LoadingSkeleton";
import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/components/ui/Button";
import {
  tableBodyDividerClass, tableHeadRowClass, tableRowHoverClass, tableTdClass, tableThClass, tableWrapperClass,
} from "@/components/ui/table";
import { WaterSubNav } from "@/components/water/WaterSubNav";
import type { NutrientMixInputCreate, NutrientMixRead } from "@/lib/api/client";
import { AppError } from "@/lib/errors/adapter";
import { formatDateTimeWithZoneLabel } from "@/lib/format/datetime";
import { humanizeEnumCode } from "@/lib/format/humanize";
import {
  useFarm,
  useInventoryItems,
  useMixesForFarm,
  useNutrientRecipeComponents,
  useNutrientRecipeVersions,
  useNutrientRecipes,
  useRecordMix,
  useReservoirs,
  useUoms,
} from "@/lib/query/hooks";

function errorMessage(error: unknown): string {
  return error instanceof AppError ? error.message : "Something went wrong. Please try again.";
}

const inputClass =
  "min-h-10 w-full rounded-md border border-wl-border bg-wl-surface-raised px-3 text-sm text-wl-text focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-wl-focus";
const labelClass = "flex flex-col gap-1 text-sm";
const labelTextClass = "text-xs font-medium uppercase tracking-wide text-wl-text-secondary";

type InputRow = { component_label: string; inventory_item_id: string; actual_quantity: string; actual_quantity_uom_id: string; note: string };

function emptyInputRow(): InputRow {
  return { component_label: "", inventory_item_id: "", actual_quantity: "", actual_quantity_uom_id: "", note: "" };
}

/** PILOT-WATER-001B: Reservoir -> optional Recipe Version (guidance only,
 * never pre-filled into actual quantities) -> operator-entered actual
 * inputs -> save. Recipe target and Mix actual are structurally two
 * different fields in two different payload shapes -- there is no code
 * path here that copies one into the other. */
function MixWorkflow({ farmId, onMixed }: { farmId: string; onMixed: (mix: NutrientMixRead) => void }) {
  const reservoirsQuery = useReservoirs(farmId);
  const recipesQuery = useNutrientRecipes();
  const uomsQuery = useUoms();
  const inventoryItemsQuery = useInventoryItems({ status: "active" });

  const [reservoirId, setReservoirId] = useState("");
  const [recipeId, setRecipeId] = useState("");
  const [recipeVersionId, setRecipeVersionId] = useState("");
  const [targetVolume, setTargetVolume] = useState("");
  const [actualVolume, setActualVolume] = useState("");
  const [volumeUomId, setVolumeUomId] = useState("");
  const [notes, setNotes] = useState("");
  const [rows, setRows] = useState<InputRow[]>([emptyInputRow()]);
  const [submitError, setSubmitError] = useState<string | null>(null);

  const versionsQuery = useNutrientRecipeVersions(recipeId || undefined);
  const componentsQuery = useNutrientRecipeComponents(recipeVersionId || undefined);
  const selectedVersion = (versionsQuery.data ?? []).find((v) => v.id === recipeVersionId);

  const recordMix = useRecordMix(farmId, reservoirId);
  const volumeUoms = (uomsQuery.data ?? []).filter((u) => u.quantity_kind === "volume");

  function updateRow(index: number, patch: Partial<InputRow>) {
    setRows((prev) => prev.map((r, i) => (i === index ? { ...r, ...patch } : r)));
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitError(null);
    if (!reservoirId) {
      setSubmitError("Choose a Reservoir / Tank first.");
      return;
    }
    const filledRows = rows.filter((r) => r.component_label.trim() && r.actual_quantity.trim() && r.actual_quantity_uom_id);
    if (filledRows.length === 0) {
      setSubmitError("Enter at least one actual input (label, quantity, unit).");
      return;
    }
    const inputs: NutrientMixInputCreate[] = filledRows.map((r, i) => ({
      component_label: r.component_label.trim(),
      inventory_item_id: r.inventory_item_id || null,
      actual_quantity: r.actual_quantity.trim(),
      actual_quantity_uom_id: r.actual_quantity_uom_id,
      sequence_number: i + 1,
      note: r.note.trim() || null,
    }));
    try {
      const mix = await recordMix.mutateAsync({
        nutrient_recipe_version_id: recipeVersionId || null,
        target_volume: targetVolume.trim() || null,
        target_volume_uom_id: targetVolume.trim() ? volumeUomId || null : null,
        actual_volume: actualVolume.trim() || null,
        actual_volume_uom_id: actualVolume.trim() ? volumeUomId || null : null,
        notes: notes.trim() || null,
        client_command_id: crypto.randomUUID(),
        inputs,
      });
      onMixed(mix);
      setRows([emptyInputRow()]);
      setActualVolume("");
      setNotes("");
    } catch (err) {
      setSubmitError(errorMessage(err));
    }
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-4 rounded-xl border border-wl-border bg-wl-surface-raised p-4">
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
        <label className={labelClass}>
          <span className={labelTextClass}>Reservoir / Tank</span>
          <select className={inputClass} value={reservoirId} onChange={(e) => setReservoirId(e.target.value)} required>
            <option value="">Select a Reservoir…</option>
            {(reservoirsQuery.data ?? []).map((r) => (
              <option key={r.id} value={r.id}>{r.code} — {r.name} ({humanizeEnumCode(r.reservoir_type)})</option>
            ))}
          </select>
        </label>

        <label className={labelClass}>
          <span className={labelTextClass}>Recipe (optional, guidance only)</span>
          <select
            className={inputClass}
            value={recipeId}
            onChange={(e) => { setRecipeId(e.target.value); setRecipeVersionId(""); }}
          >
            <option value="">No recipe reference</option>
            {(recipesQuery.data ?? []).map((r) => (
              <option key={r.id} value={r.id}>{r.code} — {r.name}</option>
            ))}
          </select>
        </label>
      </div>

      {recipeId && (
        <label className={labelClass}>
          <span className={labelTextClass}>Recipe Version</span>
          <select className={inputClass} value={recipeVersionId} onChange={(e) => setRecipeVersionId(e.target.value)}>
            <option value="">No version selected</option>
            {(versionsQuery.data ?? []).map((v) => (
              <option key={v.id} value={v.id}>
                v{v.version_number} — {humanizeEnumCode(v.state)}
              </option>
            ))}
          </select>
        </label>
      )}

      {selectedVersion && (
        <div className="rounded-lg border border-wl-border bg-wl-surface-sunken p-3 text-xs text-wl-text-secondary">
          <p className="font-medium text-wl-text">Recipe target (guidance only — never copied into actual inputs below)</p>
          <p>Target EC: {selectedVersion.target_ec ?? "not set"} · Target pH: {selectedVersion.target_ph ?? "not set"}</p>
          {(componentsQuery.data ?? []).length > 0 && (
            <ul className="mt-1 list-inside list-disc">
              {(componentsQuery.data ?? []).map((c) => (
                <li key={c.id}>{c.component_label}: target {c.target_quantity}</li>
              ))}
            </ul>
          )}
        </div>
      )}

      <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
        <label className={labelClass}>
          <span className={labelTextClass}>Target Volume</span>
          <input className={inputClass} value={targetVolume} onChange={(e) => setTargetVolume(e.target.value)} placeholder="Optional" />
        </label>
        <label className={labelClass}>
          <span className={labelTextClass}>Actual Volume</span>
          <input className={inputClass} value={actualVolume} onChange={(e) => setActualVolume(e.target.value)} placeholder="Operator-entered, optional" />
        </label>
        <label className={labelClass}>
          <span className={labelTextClass}>Volume Unit</span>
          <select className={inputClass} value={volumeUomId} onChange={(e) => setVolumeUomId(e.target.value)}>
            <option value="">Select unit…</option>
            {volumeUoms.map((u) => (
              <option key={u.id} value={u.id}>{u.code}</option>
            ))}
          </select>
        </label>
      </div>

      <div className="flex flex-col gap-3">
        <div className="flex items-baseline justify-between">
          <h3 className="text-sm font-medium text-wl-text-secondary">Actual Inputs (operator-entered)</h3>
          <button type="button" className="text-xs font-medium text-wl-brand hover:underline" onClick={() => setRows((r) => [...r, emptyInputRow()])}>
            + Add input
          </button>
        </div>
        {rows.map((row, i) => (
          <div key={i} className="grid grid-cols-1 gap-2 border-t border-wl-border pt-3 first:border-t-0 first:pt-0 md:grid-cols-5">
            <label className={labelClass}>
              <span className={labelTextClass}>Component</span>
              <input className={inputClass} value={row.component_label} onChange={(e) => updateRow(i, { component_label: e.target.value })} placeholder="e.g. Part A" />
            </label>
            <label className={labelClass}>
              <span className={labelTextClass}>Inventory Item (optional)</span>
              <select className={inputClass} value={row.inventory_item_id} onChange={(e) => updateRow(i, { inventory_item_id: e.target.value })}>
                <option value="">Not linked to Store</option>
                {(inventoryItemsQuery.data ?? []).map((item) => (
                  <option key={item.id} value={item.id}>{item.name}</option>
                ))}
              </select>
            </label>
            <label className={labelClass}>
              <span className={labelTextClass}>Actual Quantity</span>
              <input className={inputClass} value={row.actual_quantity} onChange={(e) => updateRow(i, { actual_quantity: e.target.value })} />
            </label>
            <label className={labelClass}>
              <span className={labelTextClass}>Unit</span>
              <select className={inputClass} value={row.actual_quantity_uom_id} onChange={(e) => updateRow(i, { actual_quantity_uom_id: e.target.value })}>
                <option value="">Select unit…</option>
                {(uomsQuery.data ?? []).map((u) => (
                  <option key={u.id} value={u.id}>{u.code}</option>
                ))}
              </select>
            </label>
            <label className={labelClass}>
              <span className={labelTextClass}>Note</span>
              <input className={inputClass} value={row.note} onChange={(e) => updateRow(i, { note: e.target.value })} />
            </label>
          </div>
        ))}
      </div>

      <p className="text-xs text-wl-text-tertiary">
        Recording an input here does not decrement Store inventory. This system does not yet automate Store consumption from a Mix.
      </p>

      <label className={labelClass}>
        <span className={labelTextClass}>Notes</span>
        <textarea className={`${inputClass} min-h-16`} value={notes} onChange={(e) => setNotes(e.target.value)} />
      </label>

      {submitError && <p className="text-xs text-wl-flag-fg">{submitError}</p>}

      <Button type="submit" disabled={recordMix.isPending}>
        {recordMix.isPending ? "Saving…" : "Save Mix"}
      </Button>
    </form>
  );
}

function MixResult({ farmId, mix, reservoirLabel }: { farmId: string; mix: NutrientMixRead; reservoirLabel: string }) {
  return (
    <div className="flex flex-col gap-2 rounded-xl border border-wl-border-strong bg-wl-grow-bg p-4 text-wl-grow-fg">
      <p className="text-sm font-semibold">Mix recorded for {reservoirLabel}</p>
      <p className="text-xs">
        {formatDateTimeWithZoneLabel(mix.effective_at)} · {mix.nutrient_recipe_version_id ? "Recipe-based" : "No recipe reference"} ·{" "}
        {mix.actual_volume ? `Actual volume ${mix.actual_volume}` : "Actual volume not recorded"}
      </p>
      <div className="flex flex-wrap gap-2 pt-1">
        <Link href={`/farms/${farmId}/water/measurements`} className="rounded-md border border-wl-border-strong bg-wl-surface-raised px-3 py-1.5 text-xs font-medium text-wl-text hover:bg-wl-surface-hover">
          Record Measurement
        </Link>
        <Link href={`/farms/${farmId}/water/delivery`} className="rounded-md border border-wl-border-strong bg-wl-surface-raised px-3 py-1.5 text-xs font-medium text-wl-text hover:bg-wl-surface-hover">
          Record Delivery
        </Link>
        <Link href={`/farms/${farmId}/water/setup`} className="rounded-md border border-wl-border-strong bg-wl-surface-raised px-3 py-1.5 text-xs font-medium text-wl-text hover:bg-wl-surface-hover">
          View Tank
        </Link>
      </div>
    </div>
  );
}

function RecentMixes({ farmId }: { farmId: string }) {
  const mixesQuery = useMixesForFarm(farmId);
  const reservoirsQuery = useReservoirs(farmId);
  const reservoirById = new Map((reservoirsQuery.data ?? []).map((r) => [r.id, r]));
  const rows = [...(mixesQuery.data ?? [])].sort((a, b) => new Date(b.effective_at).getTime() - new Date(a.effective_at).getTime());

  if (mixesQuery.isLoading && !mixesQuery.data) return <LoadingSkeleton rows={3} label="Loading mixes" />;
  if (mixesQuery.isError && !mixesQuery.data) return <ErrorState error={mixesQuery.error} onRetry={() => mixesQuery.refetch()} />;
  if (rows.length === 0) return <EmptyState title="No mixes recorded yet for this Farm" />;

  return (
    <div className={tableWrapperClass}>
      <table className="w-full text-sm">
        <thead>
          <tr className={tableHeadRowClass}>
            <th className={tableThClass}>Reservoir / Tank</th>
            <th className={tableThClass}>Recipe</th>
            <th className={`${tableThClass} text-right`}>Actual Volume</th>
            <th className={tableThClass}>Prepared</th>
          </tr>
        </thead>
        <tbody className={tableBodyDividerClass}>
          {rows.map((m) => {
            const reservoir = reservoirById.get(m.reservoir_id);
            return (
              <tr key={m.id} className={tableRowHoverClass}>
                <td className={tableTdClass}>{reservoir ? `${reservoir.code} — ${reservoir.name}` : m.reservoir_id.slice(0, 8)}</td>
                <td className={tableTdClass}>{m.nutrient_recipe_version_id ? "Recipe-based" : "—"}</td>
                <td className={`${tableTdClass} text-right tabular-nums`}>{m.actual_volume ?? "Not recorded"}</td>
                <td className={tableTdClass}>{formatDateTimeWithZoneLabel(m.effective_at)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export default function WaterMixingPage() {
  const { farmId } = useParams<{ farmId: string }>();
  const { data: farm } = useFarm(farmId);
  const reservoirsQuery = useReservoirs(farmId);
  const [lastMix, setLastMix] = useState<NutrientMixRead | null>(null);

  const reservoirLabel = lastMix
    ? (() => {
        const r = (reservoirsQuery.data ?? []).find((x) => x.id === lastMix.reservoir_id);
        return r ? `${r.code} — ${r.name}` : "the selected Reservoir";
      })()
    : "";

  return (
    <div>
      <PageHeader
        title="Mixing"
        description={farm ? `Record actual Nutrient Mixes for ${farm.name}` : "Record actual Nutrient Mixes"}
        breadcrumbs={
          <Breadcrumbs items={[
            { label: "Home", href: `/farms/${farmId}` },
            { label: "Water & Nutrients", href: `/farms/${farmId}/water` },
            { label: "Mixing" },
          ]}
          />
        }
      />
      <WaterSubNav farmId={farmId} />

      {lastMix && <div className="mb-4"><MixResult farmId={farmId} mix={lastMix} reservoirLabel={reservoirLabel} /></div>}

      <section className="flex flex-col gap-2">
        <h2 className="font-serif text-base font-semibold text-wl-text">Record a Mix</h2>
        <MixWorkflow farmId={farmId} onMixed={setLastMix} />
      </section>

      <section className="mt-6 flex flex-col gap-2">
        <h2 className="font-serif text-base font-semibold text-wl-text">Recent Mixes</h2>
        <RecentMixes farmId={farmId} />
      </section>
    </div>
  );
}
