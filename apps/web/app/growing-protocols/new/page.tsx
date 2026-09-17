"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { Breadcrumbs } from "@/components/Breadcrumbs";
import { ErrorState } from "@/components/ErrorState";
import { LoadingSkeleton } from "@/components/LoadingSkeleton";
import { PageHeader } from "@/components/PageHeader";
import { StandaloneShell } from "@/components/StandaloneShell";
import { Button } from "@/components/ui/Button";
import { AppError } from "@/lib/errors/adapter";
import { useCreateGrowingProtocol, useCrops, useProductionSystems, useVarieties } from "@/lib/query/hooks";

function errorMessage(error: unknown): string {
  return error instanceof AppError ? error.message : "Something went wrong. Please try again.";
}

const inputClass =
  "min-h-11 w-full rounded-md border border-wl-border bg-wl-surface-raised px-3 text-sm text-wl-text focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-wl-focus";

export default function NewGrowingProtocolPage() {
  const router = useRouter();
  const cropsQuery = useCrops();
  const productionSystemsQuery = useProductionSystems();
  const createProtocol = useCreateGrowingProtocol();

  const [code, setCode] = useState("");
  const [name, setName] = useState("");
  const [cropId, setCropId] = useState("");
  const [varietyId, setVarietyId] = useState("");
  const [productionSystemId, setProductionSystemId] = useState("");
  const [seasonContext, setSeasonContext] = useState("");
  const [serverError, setServerError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const varietiesQuery = useVarieties(cropId || undefined);
  const crops = cropsQuery.data ?? [];
  const productionSystems = productionSystemsQuery.data ?? [];
  const varieties = varietiesQuery.data ?? [];
  const isLoading = cropsQuery.isLoading || productionSystemsQuery.isLoading;

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setServerError(null);
    setIsSubmitting(true);
    try {
      const protocol = await createProtocol.mutateAsync({
        code: code.trim(),
        name: name.trim(),
        crop_id: cropId,
        variety_id: varietyId || null,
        production_system_id: productionSystemId || null,
        season_context: seasonContext.trim() || null,
      });
      router.push(`/growing-protocols/${protocol.id}`);
    } catch (error) {
      setServerError(errorMessage(error));
      setIsSubmitting(false);
    }
  }

  return (
    <StandaloneShell>
      <PageHeader
        title="New Growing Protocol"
        breadcrumbs={
          <Breadcrumbs
            items={[
              { label: "Home", href: "/farms" },
              { label: "Growing Protocols", href: "/growing-protocols" },
              { label: "New" },
            ]}
          />
        }
      />

      {isLoading && <LoadingSkeleton rows={4} label="Loading crops" />}
      {!isLoading && crops.length === 0 && (
        <ErrorState error={new AppError("invalid_request", "Register at least one crop before creating a protocol.")} />
      )}

      {!isLoading && crops.length > 0 && (
        <form
          onSubmit={handleSubmit}
          className="flex flex-col gap-4 rounded-xl border border-wl-border bg-wl-surface-raised p-4"
        >
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <label className="flex flex-col gap-1 text-sm">
              <span className="font-medium text-wl-text">Code</span>
              <input value={code} onChange={(e) => setCode(e.target.value)} className={inputClass} required />
            </label>
            <label className="flex flex-col gap-1 text-sm">
              <span className="font-medium text-wl-text">Name</span>
              <input value={name} onChange={(e) => setName(e.target.value)} className={inputClass} required />
            </label>
            <label className="flex flex-col gap-1 text-sm">
              <span className="font-medium text-wl-text">Crop</span>
              <select
                value={cropId}
                onChange={(e) => {
                  setCropId(e.target.value);
                  setVarietyId("");
                }}
                className={inputClass}
                required
              >
                <option value="">Select a crop…</option>
                {crops.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.common_name}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex flex-col gap-1 text-sm">
              <span className="font-medium text-wl-text">Variety (optional — applies to any variety if unset)</span>
              <select
                value={varietyId}
                onChange={(e) => setVarietyId(e.target.value)}
                className={inputClass}
                disabled={!cropId || varieties.length === 0}
              >
                <option value="">Any variety</option>
                {varieties.map((v) => (
                  <option key={v.id} value={v.id}>
                    {v.name}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex flex-col gap-1 text-sm">
              <span className="font-medium text-wl-text">Production system (optional)</span>
              <select value={productionSystemId} onChange={(e) => setProductionSystemId(e.target.value)} className={inputClass}>
                <option value="">Any production system</option>
                {productionSystems.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex flex-col gap-1 text-sm">
              <span className="font-medium text-wl-text">Season context (optional)</span>
              <input value={seasonContext} onChange={(e) => setSeasonContext(e.target.value)} className={inputClass} />
            </label>
          </div>

          {serverError && (
            <p role="alert" className="text-xs text-danger-700">
              {serverError}
            </p>
          )}

          <div className="flex gap-3">
            <Button type="button" variant="secondary" onClick={() => router.push("/growing-protocols")} disabled={isSubmitting}>
              Cancel
            </Button>
            <Button type="submit" variant="primary" disabled={isSubmitting || !cropId}>
              {isSubmitting ? "Creating…" : "Create protocol"}
            </Button>
          </div>
        </form>
      )}
    </StandaloneShell>
  );
}
