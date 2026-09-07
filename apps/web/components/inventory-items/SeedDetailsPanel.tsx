"use client";

import { useState } from "react";

import { Button } from "@/components/ui/Button";
import { AppError } from "@/lib/errors/adapter";
import {
  useCreateSeedProfile,
  useCrops,
  useRemoveSeedProfile,
  useSeedProfileForItem,
  useUpdateSeedProfile,
  useVarieties,
} from "@/lib/query/hooks";

function errorMessage(error: unknown): string {
  return error instanceof AppError ? error.message : "Something went wrong. Please try again.";
}

const selectClass =
  "h-9 w-full rounded-md border border-border-subtle bg-surface px-2 text-sm text-ink focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-600";

/** STORE-INV-002A.1: "Seed Details" -- the explicit, system-controlled seed
 * marker for an Inventory Item (docs/domain/STORE_INVENTORY_MODEL.md
 * §15/§F). Never inferred from Category. No status field on the backend
 * entity -- its existence alone is the signal, so this panel shows either
 * "not configured" (offer to add) or the current crop/variety (offer to
 * correct or remove) -- never an active/inactive toggle. Once the item has
 * any posted Goods Receipt, the backend locks this permanently; this panel
 * surfaces that lock as a plain, non-technical message rather than
 * predicting it client-side. */
export function SeedDetailsPanel({ itemId }: { itemId: string }) {
  const [editing, setEditing] = useState(false);
  const [cropId, setCropId] = useState("");
  const [varietyId, setVarietyId] = useState("");
  const [formError, setFormError] = useState<string | null>(null);

  const profileQuery = useSeedProfileForItem(itemId);
  const cropsQuery = useCrops();
  const varietiesQuery = useVarieties(cropId || undefined);
  const createMutation = useCreateSeedProfile();
  const updateMutation = useUpdateSeedProfile();
  const removeMutation = useRemoveSeedProfile();

  const profile = profileQuery.data ?? null;
  const crops = cropsQuery.data ?? [];
  const varieties = varietiesQuery.data ?? [];
  const isBusy = createMutation.isPending || updateMutation.isPending || removeMutation.isPending;

  function startEdit() {
    setCropId(profile?.crop_id ?? "");
    setVarietyId(profile?.variety_id ?? "");
    setFormError(null);
    setEditing(true);
  }

  function handleSave() {
    setFormError(null);
    if (!cropId || !varietyId) {
      setFormError("Crop and variety are both required.");
      return;
    }
    if (profile) {
      updateMutation.mutate(
        { profileId: profile.id, itemId, payload: { client_command_id: crypto.randomUUID(), crop_id: cropId, variety_id: varietyId } },
        { onSuccess: () => setEditing(false), onError: (error) => setFormError(errorMessage(error)) },
      );
    } else {
      createMutation.mutate(
        { client_command_id: crypto.randomUUID(), inventory_item_id: itemId, crop_id: cropId, variety_id: varietyId },
        { onSuccess: () => setEditing(false), onError: (error) => setFormError(errorMessage(error)) },
      );
    }
  }

  function handleRemove() {
    if (!profile) return;
    setFormError(null);
    removeMutation.mutate(
      { profileId: profile.id, itemId, payload: { client_command_id: crypto.randomUUID() } },
      { onError: (error) => setFormError(errorMessage(error)) },
    );
  }

  const cropName = crops.find((c) => c.id === profile?.crop_id)?.common_name ?? profile?.crop_id;

  return (
    <div className="mt-4 rounded-xl border border-border-subtle bg-surface p-4">
      <h4 className="mb-2 text-sm font-semibold text-ink">Seed Details</h4>

      {profileQuery.isLoading && <p className="text-xs text-ink-muted">Loading Seed Details…</p>}

      {!profileQuery.isLoading && !editing && (
        <div className="flex items-center justify-between gap-2">
          <p className="text-sm text-ink">
            {profile ? (
              <>
                This item is seed -- <span className="font-medium">{cropName}</span>
              </>
            ) : (
              <span className="text-ink-muted">This item is not configured as seed.</span>
            )}
          </p>
          <div className="flex gap-2">
            <Button variant="secondary" onClick={startEdit}>
              {profile ? "Correct" : "Mark as seed"}
            </Button>
            {profile && (
              <Button variant="secondary" disabled={isBusy} onClick={handleRemove}>
                Remove
              </Button>
            )}
          </div>
        </div>
      )}

      {editing && (
        <div className="flex flex-wrap items-end gap-2">
          <label className="flex flex-col gap-1 text-xs text-ink-muted">
            Crop
            <select className={selectClass} value={cropId} onChange={(e) => { setCropId(e.target.value); setVarietyId(""); }}>
              <option value="">Select crop…</option>
              {crops.map((crop) => (
                <option key={crop.id} value={crop.id}>
                  {crop.common_name}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1 text-xs text-ink-muted">
            Variety
            <select className={selectClass} value={varietyId} onChange={(e) => setVarietyId(e.target.value)} disabled={!cropId}>
              <option value="">Select variety…</option>
              {varieties.map((variety) => (
                <option key={variety.id} value={variety.id}>
                  {variety.name}
                </option>
              ))}
            </select>
          </label>
          <Button variant="primary" disabled={isBusy} onClick={handleSave}>
            Save
          </Button>
          <Button variant="secondary" onClick={() => setEditing(false)}>
            Cancel
          </Button>
        </div>
      )}

      {formError && (
        <p className="mt-2 text-xs text-red-700">
          {formError.toLowerCase().includes("locked") || formError.toLowerCase().includes("frozen")
            ? "This item has already been received into inventory and can no longer change its seed configuration. Deactivate this item and create a replacement if this needs correcting."
            : formError}
        </p>
      )}
    </div>
  );
}
