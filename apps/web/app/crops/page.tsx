"use client";

import { PlusCircle } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { Breadcrumbs } from "@/components/Breadcrumbs";
import { CropForm } from "@/components/crops/CropForm";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { LoadingSkeleton } from "@/components/LoadingSkeleton";
import { PageHeader } from "@/components/PageHeader";
import { StandaloneShell } from "@/components/StandaloneShell";
import { StatusBadge, type StatusTone } from "@/components/StatusBadge";
import { Button } from "@/components/ui/Button";
import type { CropCreate } from "@/lib/api/client";
import { AppError } from "@/lib/errors/adapter";
import { useCreateCrop, useCrops } from "@/lib/query/hooks";

function errorMessage(error: unknown): string {
  return error instanceof AppError ? error.message : "Something went wrong. Please try again.";
}

const CROP_CATEGORY_LABELS: Record<string, string> = {
  leafy_green: "Leafy green",
  vine: "Vine",
  herb: "Herb",
  other: "Other",
};

/** PILOT-SETUP-001B6: tenant-level Crop master data -- crop-agnostic by
 * design (no per-crop branch anywhere on this page; Iceberg lettuce is
 * ordinary `leafy_green` configuration data entered through this same
 * form). Creates Crop master data only -- never a Crop Batch, Sowing, or
 * Seed Lot. */
export default function CropsPage() {
  const [creating, setCreating] = useState(false);
  const [serverError, setServerError] = useState<string | null>(null);

  const cropsQuery = useCrops();
  const createMutation = useCreateCrop();
  const crops = cropsQuery.data ?? [];

  function handleSubmit(payload: CropCreate) {
    setServerError(null);
    createMutation.mutate(payload, {
      onSuccess: () => setCreating(false),
      onError: (error) => setServerError(errorMessage(error)),
    });
  }

  return (
    <StandaloneShell>
      <PageHeader
        title="Crops"
        breadcrumbs={<Breadcrumbs items={[{ label: "Home", href: "/farms" }, { label: "Crops" }]} />}
        actions={
          !creating && (
            <Button variant="primary" onClick={() => setCreating(true)}>
              <PlusCircle aria-hidden="true" className="h-4 w-4" />
              New crop
            </Button>
          )
        }
      />
      <p className="-mt-3 mb-6 text-xs text-ink-muted">
        Tenant-wide crop catalog. Select a crop to manage its varieties.
      </p>

      {creating && (
        <CropForm
          isSubmitting={createMutation.isPending}
          serverError={serverError}
          onCancel={() => {
            setCreating(false);
            setServerError(null);
          }}
          onSubmit={handleSubmit}
        />
      )}

      {!creating && (
        <>
          {cropsQuery.isLoading && <LoadingSkeleton rows={4} label="Loading crops" />}
          {cropsQuery.error && <ErrorState error={cropsQuery.error} onRetry={() => cropsQuery.refetch()} />}
          {!cropsQuery.isLoading && !cropsQuery.error && crops.length === 0 && (
            <EmptyState
              title="No crops yet"
              description="Register the first crop before configuring varieties or a workflow."
            />
          )}
          {!cropsQuery.isLoading && !cropsQuery.error && crops.length > 0 && (
            <div className="overflow-x-auto rounded-xl border border-border-subtle bg-surface">
              <table className="w-full text-left text-sm">
                <thead className="border-b border-border-subtle bg-surface-subtle text-xs uppercase text-ink-muted">
                  <tr>
                    <th className="px-4 py-2 font-medium">Code</th>
                    <th className="px-4 py-2 font-medium">Common name</th>
                    <th className="px-4 py-2 font-medium">Category</th>
                    <th className="px-4 py-2 font-medium">Status</th>
                    <th className="px-4 py-2 font-medium" />
                  </tr>
                </thead>
                <tbody className="divide-y divide-border-subtle">
                  {crops.map((crop) => {
                    const tone: StatusTone = crop.status === "active" ? "active" : "closed";
                    return (
                      <tr key={crop.id} className="hover:bg-surface-subtle">
                        <td className="px-4 py-2 font-medium text-ink">{crop.code}</td>
                        <td className="px-4 py-2 text-ink">{crop.common_name}</td>
                        <td className="px-4 py-2 text-ink-muted">
                          {CROP_CATEGORY_LABELS[crop.crop_category] ?? crop.crop_category}
                        </td>
                        <td className="px-4 py-2">
                          <StatusBadge label={crop.status === "active" ? "Active" : "Inactive"} tone={tone} />
                        </td>
                        <td className="px-4 py-2">
                          <Link
                            href={`/crops/${crop.id}`}
                            className="text-sm font-medium text-brand-700 hover:underline"
                          >
                            Varieties
                          </Link>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </StandaloneShell>
  );
}
