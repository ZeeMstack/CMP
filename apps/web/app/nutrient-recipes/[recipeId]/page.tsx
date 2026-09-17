"use client";

import { useParams } from "next/navigation";
import { useState } from "react";

import { Breadcrumbs } from "@/components/Breadcrumbs";
import { ErrorState } from "@/components/ErrorState";
import { LoadingSkeleton } from "@/components/LoadingSkeleton";
import { PageHeader } from "@/components/PageHeader";
import { StandaloneShell } from "@/components/StandaloneShell";
import { StatusBadge, type StatusTone } from "@/components/StatusBadge";
import { Button } from "@/components/ui/Button";
import type { NutrientRecipeComponentCreate, NutrientRecipeVersionRead } from "@/lib/api/client";
import { AppError } from "@/lib/errors/adapter";
import {
  useActivateNutrientRecipeVersion,
  useAddNutrientRecipeComponent,
  useCreateNutrientRecipeVersion,
  useInventoryItems,
  useNutrientRecipe,
  useNutrientRecipeComponents,
  useNutrientRecipeVersions,
  useRetireNutrientRecipeVersion,
  useUoms,
} from "@/lib/query/hooks";

function errorMessage(error: unknown): string {
  return error instanceof AppError ? error.message : "Something went wrong. Please try again.";
}

const inputClass =
  "min-h-9 w-full rounded-md border border-wl-border bg-wl-surface-raised px-3 text-sm text-wl-text focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-wl-focus";

function versionStateTone(state: string): StatusTone {
  if (state === "active") return "active";
  if (state === "draft") return "attention";
  return "closed";
}

function ComponentsList({ versionId, editable }: { versionId: string; editable: boolean }) {
  const componentsQuery = useNutrientRecipeComponents(versionId);
  const inventoryItemsQuery = useInventoryItems({ status: "active" });
  const uomsQuery = useUoms();
  const addComponent = useAddNutrientRecipeComponent(versionId);

  const [label, setLabel] = useState("");
  const [inventoryItemId, setInventoryItemId] = useState("");
  const [quantity, setQuantity] = useState("");
  const [uomId, setUomId] = useState("");
  const [submitError, setSubmitError] = useState<string | null>(null);

  async function handleAdd(e: React.FormEvent) {
    e.preventDefault();
    setSubmitError(null);
    if (!label.trim() || !quantity.trim() || !uomId) {
      setSubmitError("Component label, target quantity and unit are required.");
      return;
    }
    const payload: NutrientRecipeComponentCreate = {
      component_label: label.trim(),
      inventory_item_id: inventoryItemId || null,
      target_quantity: quantity.trim(),
      target_quantity_uom_id: uomId,
    };
    try {
      await addComponent.mutateAsync(payload);
      setLabel("");
      setInventoryItemId("");
      setQuantity("");
    } catch (err) {
      setSubmitError(errorMessage(err));
    }
  }

  return (
    <div className="flex flex-col gap-2">
      {(componentsQuery.data ?? []).length === 0 ? (
        <p className="text-xs text-wl-text-tertiary">No target components recorded.</p>
      ) : (
        <ul className="flex flex-col gap-1 text-sm">
          {(componentsQuery.data ?? []).map((c) => (
            <li key={c.id} className="flex justify-between gap-2 text-wl-text">
              <span>{c.component_label}</span>
              <span className="tabular-nums text-wl-text-secondary">{c.target_quantity}</span>
            </li>
          ))}
        </ul>
      )}

      {editable && (
        <form onSubmit={handleAdd} className="mt-2 grid grid-cols-1 gap-2 rounded-lg border border-wl-border bg-wl-surface-sunken p-3 md:grid-cols-4">
          <input className={inputClass} placeholder="Component label" value={label} onChange={(e) => setLabel(e.target.value)} />
          <select className={inputClass} value={inventoryItemId} onChange={(e) => setInventoryItemId(e.target.value)}>
            <option value="">Not linked to Store</option>
            {(inventoryItemsQuery.data ?? []).map((item) => (
              <option key={item.id} value={item.id}>{item.name}</option>
            ))}
          </select>
          <input className={inputClass} placeholder="Target quantity" value={quantity} onChange={(e) => setQuantity(e.target.value)} />
          <div className="flex gap-2">
            <select className={inputClass} value={uomId} onChange={(e) => setUomId(e.target.value)}>
              <option value="">Unit…</option>
              {(uomsQuery.data ?? []).map((u) => (
                <option key={u.id} value={u.id}>{u.code}</option>
              ))}
            </select>
            <Button type="submit" disabled={addComponent.isPending}>Add</Button>
          </div>
          {submitError && <p className="col-span-full text-xs text-wl-flag-fg">{submitError}</p>}
        </form>
      )}
    </div>
  );
}

function VersionCard({ recipeId, version }: { recipeId: string; version: NutrientRecipeVersionRead }) {
  const [expanded, setExpanded] = useState(version.state !== "retired");
  const [actionError, setActionError] = useState<string | null>(null);
  const activate = useActivateNutrientRecipeVersion(recipeId);
  const retire = useRetireNutrientRecipeVersion(recipeId);
  const editable = version.state === "draft";

  async function handleActivate() {
    setActionError(null);
    try {
      await activate.mutateAsync({ versionId: version.id, payload: { client_command_id: crypto.randomUUID() } });
    } catch (err) {
      setActionError(errorMessage(err));
    }
  }
  async function handleRetire() {
    setActionError(null);
    try {
      await retire.mutateAsync({ versionId: version.id, payload: { client_command_id: crypto.randomUUID() } });
    } catch (err) {
      setActionError(errorMessage(err));
    }
  }

  return (
    <li className="flex flex-col gap-3 px-4 py-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <button type="button" className="flex items-center gap-2 text-left" onClick={() => setExpanded((e) => !e)}>
          <span className="text-sm font-medium text-wl-text">Version {version.version_number}</span>
          <StatusBadge label={version.state} tone={versionStateTone(version.state)} />
        </button>
        <div className="flex gap-2">
          {version.state === "draft" && (
            <Button variant="primary" onClick={handleActivate} disabled={activate.isPending}>
              {activate.isPending ? "Activating…" : "Activate"}
            </Button>
          )}
          {version.state === "active" && (
            <Button onClick={handleRetire} disabled={retire.isPending}>
              {retire.isPending ? "Retiring…" : "Retire"}
            </Button>
          )}
        </div>
      </div>
      <p className="text-xs text-wl-text-secondary">{version.reason}</p>
      {actionError && <p className="text-xs text-wl-flag-fg">{actionError}</p>}

      {expanded && (
        <div className="rounded-lg border border-wl-border bg-wl-surface-raised p-3">
          <p className="text-xs text-wl-text-secondary">
            Target EC: {version.target_ec ?? "not set"} · Target pH: {version.target_ph ?? "not set"}
            {!editable && " (ACTIVE — read-only)"}
          </p>
          {version.instructions && <p className="mt-1 text-xs text-wl-text-tertiary">{version.instructions}</p>}
          <div className="mt-3">
            <h4 className="mb-1 text-xs font-medium uppercase tracking-wide text-wl-text-secondary">Target Components</h4>
            <ComponentsList versionId={version.id} editable={editable} />
          </div>
        </div>
      )}
    </li>
  );
}

/** PILOT-WATER-001B: Nutrient Recipe detail -- versions (draft/active/
 * retired), guidance-only components, activate/retire. Mirrors Growing
 * Protocol's own shell/version-catalog split. Every value shown here is a
 * TARGET; nothing on this page can create or edit a Mix's actual
 * quantities -- that happens only on the Mixing workflow, operator-entered. */
export default function NutrientRecipeDetailPage() {
  const { recipeId } = useParams<{ recipeId: string }>();
  const recipeQuery = useNutrientRecipe(recipeId);
  const versionsQuery = useNutrientRecipeVersions(recipeId);
  const createVersion = useCreateNutrientRecipeVersion(recipeId);
  const [actionError, setActionError] = useState<string | null>(null);

  if (recipeQuery.isLoading) return <StandaloneShell><LoadingSkeleton rows={4} label="Loading recipe" /></StandaloneShell>;
  if (recipeQuery.error) {
    return (
      <StandaloneShell>
        <ErrorState error={recipeQuery.error} onRetry={() => recipeQuery.refetch()} />
      </StandaloneShell>
    );
  }
  const recipe = recipeQuery.data;
  if (!recipe) return null;

  const versions = versionsQuery.data ?? [];

  async function handleCreateDraft() {
    setActionError(null);
    const reason = window.prompt("Reason for this new draft version:");
    if (!reason || !reason.trim()) return;
    try {
      await createVersion.mutateAsync({ client_command_id: crypto.randomUUID(), reason: reason.trim(), effective_date: null });
    } catch (err) {
      setActionError(errorMessage(err));
    }
  }

  return (
    <StandaloneShell>
      <PageHeader
        title={recipe.name}
        description={recipe.code}
        breadcrumbs={
          <Breadcrumbs items={[
            { label: "Home", href: "/farms" },
            { label: "Nutrient Recipes", href: "/nutrient-recipes" },
            { label: recipe.code },
          ]}
          />
        }
        actions={
          <Button variant="primary" onClick={handleCreateDraft} disabled={createVersion.isPending}>
            {createVersion.isPending ? "Creating…" : "Create Draft Version"}
          </Button>
        }
      />

      {actionError && <p role="alert" className="mb-4 text-xs text-wl-flag-fg">{actionError}</p>}

      {versionsQuery.isLoading && !versionsQuery.data && <LoadingSkeleton rows={3} label="Loading versions" />}
      {versionsQuery.isError && !versionsQuery.data && <ErrorState error={versionsQuery.error} onRetry={() => versionsQuery.refetch()} />}
      {versionsQuery.data && versions.length === 0 && (
        <p className="text-sm text-wl-text-secondary">No versions yet — create the first draft above.</p>
      )}
      {versions.length > 0 && (
        <ul className="divide-y divide-wl-border rounded-xl border border-wl-border bg-wl-surface-raised">
          {[...versions].reverse().map((version) => (
            <VersionCard key={version.id} recipeId={recipeId} version={version} />
          ))}
        </ul>
      )}
    </StandaloneShell>
  );
}
