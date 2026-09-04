"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useEffect } from "react";
import { useForm, useWatch, type Path, type UseFormRegister, type UseFormSetValue } from "react-hook-form";

import { Button } from "@/components/ui/Button";
import type { InventoryCategoryRead, InventoryItemCreate, InventoryItemRead, InventoryItemUpdate, UnitOfMeasureRead } from "@/lib/api/client";
import {
  buildInventoryItemCreatePayload,
  buildInventoryItemUpdatePayload,
  inventoryItemFormSchema,
  inventoryItemUpdateFormSchema,
  type InventoryItemFormValues,
  type InventoryItemUpdateFormValues,
} from "@/lib/validation/inventoryItem";

const inputClass =
  "min-h-11 w-full rounded-md border border-border-subtle bg-surface px-3 text-sm text-ink focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-600 disabled:cursor-not-allowed disabled:bg-surface-subtle disabled:text-ink-muted";
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

/** docs/domain/STORE_INVENTORY_MODEL.md §5: enabling Expiry Tracking or QC
 * Release must auto-require (and lock) Lot Tracking on -- the UI never lets
 * an operator submit the invalid combination and rely on the backend's 422.
 * Shared by both the create and update forms below. */
type TrackingFields = {
  lotTrackingRequired: boolean;
  expiryTrackingRequired: boolean;
  qcReleaseRequired: boolean;
};

function TrackingPolicyFields<T extends TrackingFields>({
  register,
  setValue,
  lotTrackingRequired,
  expiryTrackingRequired,
  qcReleaseRequired,
  error,
}: {
  register: UseFormRegister<T>;
  setValue: UseFormSetValue<T>;
  lotTrackingRequired: boolean;
  expiryTrackingRequired: boolean;
  qcReleaseRequired: boolean;
  error?: string;
}) {
  const lotTrackingForced = expiryTrackingRequired || qcReleaseRequired;

  useEffect(() => {
    if (lotTrackingForced && !lotTrackingRequired) {
      setValue("lotTrackingRequired" as Path<T>, true as never);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lotTrackingForced]);

  return (
    <fieldset className="flex flex-col gap-3 rounded-xl border border-border-subtle bg-surface p-4">
      <legend className="px-1 text-sm font-semibold text-ink">Tracking policy</legend>
      <label className="flex items-center gap-2 text-sm text-ink">
        <input
          type="checkbox"
          {...register("lotTrackingRequired" as Path<T>)}
          disabled={lotTrackingForced}
          checked={lotTrackingRequired}
        />
        Lot tracking required
        {lotTrackingForced && (
          <span className="text-xs text-ink-muted">(required by Expiry Tracking / QC Release)</span>
        )}
      </label>
      <label className="flex items-center gap-2 text-sm text-ink">
        <input type="checkbox" {...register("expiryTrackingRequired" as Path<T>)} />
        Expiry tracking required
      </label>
      <label className="flex items-center gap-2 text-sm text-ink">
        <input type="checkbox" {...register("qcReleaseRequired" as Path<T>)} />
        QC release required
      </label>
      {error && <span className={errorClass}>{error}</span>}
    </fieldset>
  );
}

export function InventoryItemForm({
  categories,
  uoms,
  onSubmit,
  onCancel,
  isSubmitting,
  serverError,
}: {
  categories: InventoryCategoryRead[];
  uoms: UnitOfMeasureRead[];
  onSubmit: (payload: InventoryItemCreate) => void;
  onCancel: () => void;
  isSubmitting: boolean;
  serverError?: string | null;
}) {
  const {
    register,
    control,
    setValue,
    handleSubmit,
    formState: { errors },
  } = useForm<InventoryItemFormValues>({
    resolver: zodResolver(inventoryItemFormSchema),
    defaultValues: {
      code: "", name: "", categoryId: "", baseUomId: "", lotTrackingRequired: false,
      expiryTrackingRequired: false, qcReleaseRequired: false,
    },
    mode: "onBlur",
  });

  const lotTrackingRequired = useWatch({ control, name: "lotTrackingRequired" });
  const expiryTrackingRequired = useWatch({ control, name: "expiryTrackingRequired" });
  const qcReleaseRequired = useWatch({ control, name: "qcReleaseRequired" });

  function submit(values: InventoryItemFormValues) {
    onSubmit(buildInventoryItemCreatePayload(values, crypto.randomUUID()));
  }

  return (
    <form onSubmit={handleSubmit(submit)} className="flex flex-col gap-6">
      <fieldset className="grid grid-cols-1 gap-4 rounded-xl border border-border-subtle bg-surface p-4 sm:grid-cols-2">
        <legend className="px-1 text-sm font-semibold text-ink">Item identity</legend>
        <Field label="Code" error={errors.code?.message}>
          <input {...register("code")} className={inputClass} placeholder="MAMUTIK-SEED" />
        </Field>
        <Field label="Name" error={errors.name?.message}>
          <input {...register("name")} className={inputClass} placeholder="Mamutik Seed" />
        </Field>
        <Field label="Category" error={errors.categoryId?.message}>
          <select {...register("categoryId")} className={inputClass}>
            <option value="">Select a category…</option>
            {categories.map((c) => (
              <option key={c.id} value={c.id}>{c.name}</option>
            ))}
          </select>
        </Field>
        <Field label="Base unit of measure" error={errors.baseUomId?.message}>
          <select {...register("baseUomId")} className={inputClass}>
            <option value="">Select a unit…</option>
            {uoms.map((u) => (
              <option key={u.id} value={u.id}>{u.code} — {u.name}</option>
            ))}
          </select>
        </Field>
      </fieldset>

      <TrackingPolicyFields
        register={register}
        setValue={setValue}
        lotTrackingRequired={lotTrackingRequired}
        expiryTrackingRequired={expiryTrackingRequired}
        qcReleaseRequired={qcReleaseRequired}
        error={errors.lotTrackingRequired?.message}
      />

      {serverError && (
        <p role="alert" className={errorClass}>
          {serverError}
        </p>
      )}

      <div className="flex gap-3">
        <Button type="button" variant="secondary" onClick={onCancel} disabled={isSubmitting}>
          Cancel
        </Button>
        <Button type="submit" variant="primary" disabled={isSubmitting}>
          {isSubmitting ? "Creating…" : "Create item"}
        </Button>
      </div>
    </form>
  );
}

export function InventoryItemEditForm({
  item,
  categories,
  uoms,
  onSubmit,
  onCancel,
  isSubmitting,
  serverError,
}: {
  item: InventoryItemRead;
  categories: InventoryCategoryRead[];
  uoms: UnitOfMeasureRead[];
  onSubmit: (payload: InventoryItemUpdate) => void;
  onCancel: () => void;
  isSubmitting: boolean;
  serverError?: string | null;
}) {
  const {
    register,
    control,
    setValue,
    handleSubmit,
    formState: { errors },
  } = useForm<InventoryItemUpdateFormValues>({
    resolver: zodResolver(inventoryItemUpdateFormSchema),
    defaultValues: {
      name: item.name,
      categoryId: item.inventory_category_id,
      baseUomId: item.base_uom_id,
      lotTrackingRequired: item.lot_tracking_required,
      expiryTrackingRequired: item.expiry_tracking_required,
      qcReleaseRequired: item.qc_release_required,
    },
    mode: "onBlur",
  });

  const lotTrackingRequired = useWatch({ control, name: "lotTrackingRequired" });
  const expiryTrackingRequired = useWatch({ control, name: "expiryTrackingRequired" });
  const qcReleaseRequired = useWatch({ control, name: "qcReleaseRequired" });

  function submit(values: InventoryItemUpdateFormValues) {
    onSubmit(buildInventoryItemUpdatePayload(values, crypto.randomUUID()));
  }

  return (
    <form onSubmit={handleSubmit(submit)} className="flex flex-col gap-6">
      <fieldset className="grid grid-cols-1 gap-4 rounded-xl border border-border-subtle bg-surface p-4 sm:grid-cols-2">
        <legend className="px-1 text-sm font-semibold text-ink">
          Editing {item.code} <span className="text-xs text-ink-muted">(code is never editable)</span>
        </legend>
        <Field label="Name" error={errors.name?.message}>
          <input {...register("name")} className={inputClass} />
        </Field>
        <Field label="Category" error={errors.categoryId?.message}>
          <select {...register("categoryId")} className={inputClass}>
            {categories.map((c) => (
              <option key={c.id} value={c.id}>{c.name}</option>
            ))}
          </select>
        </Field>
        <Field label="Base unit of measure" error={errors.baseUomId?.message}>
          <select {...register("baseUomId")} className={inputClass}>
            {uoms.map((u) => (
              <option key={u.id} value={u.id}>{u.code} — {u.name}</option>
            ))}
          </select>
        </Field>
      </fieldset>

      <TrackingPolicyFields
        register={register}
        setValue={setValue}
        lotTrackingRequired={lotTrackingRequired}
        expiryTrackingRequired={expiryTrackingRequired}
        qcReleaseRequired={qcReleaseRequired}
        error={errors.lotTrackingRequired?.message}
      />

      {serverError && (
        <p role="alert" className={errorClass}>
          {serverError}
        </p>
      )}

      <div className="flex gap-3">
        <Button type="button" variant="secondary" onClick={onCancel} disabled={isSubmitting}>
          Cancel
        </Button>
        <Button type="submit" variant="primary" disabled={isSubmitting}>
          {isSubmitting ? "Saving…" : "Save changes"}
        </Button>
      </div>
    </form>
  );
}
