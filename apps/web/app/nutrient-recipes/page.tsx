"use client";

import { PlusCircle } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { Breadcrumbs } from "@/components/Breadcrumbs";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { LoadingSkeleton } from "@/components/LoadingSkeleton";
import { PageHeader } from "@/components/PageHeader";
import { StandaloneShell } from "@/components/StandaloneShell";
import { StatusBadge } from "@/components/StatusBadge";
import { Button } from "@/components/ui/Button";
import {
  tableBodyDividerClass, tableHeadRowClass, tableRowHoverClass, tableTdClass, tableThClass, tableWrapperClass,
} from "@/components/ui/table";
import type { NutrientRecipeCreate } from "@/lib/api/client";
import { AppError } from "@/lib/errors/adapter";
import { useCreateNutrientRecipe, useCrops, useNutrientRecipes, useProductionSystems } from "@/lib/query/hooks";

function errorMessage(error: unknown): string {
  return error instanceof AppError ? error.message : "Something went wrong. Please try again.";
}

const inputClass =
  "min-h-10 w-full rounded-md border border-wl-border bg-wl-surface-raised px-3 text-sm text-wl-text focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-wl-focus";
const labelClass = "flex flex-col gap-1 text-sm";
const labelTextClass = "text-xs font-medium uppercase tracking-wide text-wl-text-secondary";

function NewRecipeForm({ onClose }: { onClose: () => void }) {
  const cropsQuery = useCrops();
  const productionSystemsQuery = useProductionSystems();
  const createRecipe = useCreateNutrientRecipe();

  const [code, setCode] = useState("");
  const [name, setName] = useState("");
  const [cropId, setCropId] = useState("");
  const [productionSystemId, setProductionSystemId] = useState("");
  const [submitError, setSubmitError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitError(null);
    const payload: NutrientRecipeCreate = {
      code: code.trim(),
      name: name.trim(),
      crop_id: cropId || null,
      production_system_id: productionSystemId || null,
    };
    try {
      await createRecipe.mutateAsync(payload);
      onClose();
    } catch (err) {
      setSubmitError(errorMessage(err));
    }
  }

  return (
    <form onSubmit={handleSubmit} className="mb-6 flex flex-col gap-3 rounded-xl border border-wl-border bg-wl-surface-raised p-4">
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
        <label className={labelClass}>
          <span className={labelTextClass}>Code</span>
          <input className={inputClass} value={code} onChange={(e) => setCode(e.target.value)} required />
        </label>
        <label className={labelClass}>
          <span className={labelTextClass}>Name</span>
          <input className={inputClass} value={name} onChange={(e) => setName(e.target.value)} required />
        </label>
        <label className={labelClass}>
          <span className={labelTextClass}>Crop (optional)</span>
          <select className={inputClass} value={cropId} onChange={(e) => setCropId(e.target.value)}>
            <option value="">Any crop</option>
            {(cropsQuery.data ?? []).map((c) => (
              <option key={c.id} value={c.id}>{c.common_name}</option>
            ))}
          </select>
        </label>
        <label className={labelClass}>
          <span className={labelTextClass}>Production System (optional)</span>
          <select className={inputClass} value={productionSystemId} onChange={(e) => setProductionSystemId(e.target.value)}>
            <option value="">Any production system</option>
            {(productionSystemsQuery.data ?? []).map((p) => (
              <option key={p.id} value={p.id}>{p.name}</option>
            ))}
          </select>
        </label>
      </div>
      {submitError && <p className="text-xs text-wl-flag-fg">{submitError}</p>}
      <div className="flex gap-2">
        <Button type="submit" variant="primary" disabled={createRecipe.isPending}>
          {createRecipe.isPending ? "Creating…" : "Create Recipe"}
        </Button>
        <Button type="button" onClick={onClose}>Cancel</Button>
      </div>
    </form>
  );
}

/** PILOT-WATER-001B: tenant/company-level Nutrient Recipe catalog, mirroring
 * Growing Protocols' own route shape and admin pattern exactly (same
 * StandaloneShell, same list -> detail -> versions structure). A Recipe
 * here is target guidance only -- it never becomes an actual Mix without an
 * operator explicitly entering actual quantities on the Mixing page. */
export default function NutrientRecipesPage() {
  const recipesQuery = useNutrientRecipes();
  const cropsQuery = useCrops();
  const [showNew, setShowNew] = useState(false);

  const recipes = recipesQuery.data ?? [];
  const crops = cropsQuery.data ?? [];
  const isLoading = recipesQuery.isLoading && !recipesQuery.data;
  const loadError = recipesQuery.isError && !recipesQuery.data ? recipesQuery.error : null;

  return (
    <StandaloneShell>
      <PageHeader
        title="Nutrient Recipes"
        breadcrumbs={<Breadcrumbs items={[{ label: "Home", href: "/farms" }, { label: "Nutrient Recipes" }]} />}
        actions={
          <Button variant="primary" onClick={() => setShowNew((s) => !s)}>
            <PlusCircle aria-hidden="true" className="h-4 w-4" />
            New recipe
          </Button>
        }
      />
      <p className="-mt-3 mb-6 text-xs text-wl-text-secondary">
        Tenant-wide nutrient guidance catalog: target EC/pH/components a Reservoir Mix can reference. Activating a
        version here never changes any already-recorded Mix, and never auto-fills a Mix&apos;s actual quantities.
      </p>

      {showNew && <NewRecipeForm onClose={() => setShowNew(false)} />}

      {isLoading && <LoadingSkeleton rows={4} label="Loading nutrient recipes" />}
      {loadError && <ErrorState error={loadError} onRetry={() => recipesQuery.refetch()} />}

      {!isLoading && !loadError && recipes.length === 0 && (
        <EmptyState title="No nutrient recipes yet" description="Create the first recipe to start versioning target EC/pH/components." />
      )}

      {!isLoading && !loadError && recipes.length > 0 && (
        <div className={tableWrapperClass}>
          <table className="w-full text-left text-sm">
            <thead>
              <tr className={tableHeadRowClass}>
                <th className={tableThClass}>Code</th>
                <th className={tableThClass}>Name</th>
                <th className={tableThClass}>Crop</th>
                <th className={tableThClass}>Status</th>
                <th className={tableThClass} />
              </tr>
            </thead>
            <tbody className={tableBodyDividerClass}>
              {recipes.map((recipe) => {
                const crop = crops.find((c) => c.id === recipe.crop_id);
                return (
                  <tr key={recipe.id} className={tableRowHoverClass}>
                    <td className={`${tableTdClass} font-medium text-wl-text`}>{recipe.code}</td>
                    <td className={`${tableTdClass} text-wl-text`}>{recipe.name}</td>
                    <td className={`${tableTdClass} text-wl-text-secondary`}>{crop ? crop.common_name : "Any"}</td>
                    <td className={tableTdClass}>
                      <StatusBadge label={recipe.status === "active" ? "Active" : "Inactive"} tone={recipe.status === "active" ? "active" : "closed"} />
                    </td>
                    <td className={tableTdClass}>
                      <Link href={`/nutrient-recipes/${recipe.id}`} className="text-sm font-medium text-wl-brand hover:underline">
                        Open
                      </Link>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </StandaloneShell>
  );
}
