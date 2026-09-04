"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { useForm, useWatch } from "react-hook-form";

import { Button } from "@/components/ui/Button";
import type { LocationBulkChildrenCreate, LocationCreate } from "@/lib/api/client";
import type { FlattenedStoreOption } from "@/lib/format/storeTree";
import {
  type AddAreaFormValues,
  type AddBinFormValues,
  type AddRackFormValues,
  DEFAULT_ADD_BIN_FORM_VALUES,
  type NewStoreFormValues,
  addAreaFormSchema,
  addBinFormSchema,
  addRackFormSchema,
  buildAddAreaPayload,
  buildAddBinBulkPayload,
  buildAddBinSinglePayload,
  buildAddRackPayload,
  buildNewStorePayload,
  newStoreFormSchema,
} from "@/lib/validation/storeLocation";

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

type StoreAction = "store" | "area" | "rack" | "bin";

/** docs/domain/STORE_INVENTORY_MODEL.md §9: a purpose-built, constrained
 * counterpart to the generic `LocationCreateForm` -- each action below
 * hardcodes its one legal `location_type_code` and only ever offers
 * parents of a type that action actually permits, rather than a free-text
 * type picker over the whole farm tree waiting on a backend 422. */
export function StoreCreateForm({
  storeRoots,
  areaAndStoreOptions,
  anyParentOptions,
  isSubmitting,
  serverError,
  onCancel,
  onSubmitStore,
  onSubmitArea,
  onSubmitRack,
  onSubmitBinSingle,
  onSubmitBinBulk,
}: {
  storeRoots: FlattenedStoreOption[];
  areaAndStoreOptions: FlattenedStoreOption[];
  anyParentOptions: FlattenedStoreOption[];
  isSubmitting: boolean;
  serverError?: string | null;
  onCancel: () => void;
  onSubmitStore: (payload: LocationCreate) => void;
  onSubmitArea: (payload: LocationCreate) => void;
  onSubmitRack: (payload: LocationCreate) => void;
  onSubmitBinSingle: (payload: LocationCreate) => void;
  onSubmitBinBulk: (parentId: string, payload: LocationBulkChildrenCreate) => void;
}) {
  const [action, setAction] = useState<StoreAction>("store");

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap gap-2" role="tablist" aria-label="Store hierarchy action">
        {(
          [
            ["store", "New Store"],
            ["area", "Add Area"],
            ["rack", "Add Rack"],
            ["bin", "Add Bin(s)"],
          ] as const
        ).map(([value, label]) => (
          <button
            key={value}
            type="button"
            role="tab"
            aria-selected={action === value}
            onClick={() => setAction(value)}
            className={`min-h-9 rounded-full px-4 text-sm font-medium ${
              action === value ? "bg-brand-600 text-white" : "border border-border-subtle bg-surface text-ink"
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {action === "store" && (
        <NewStoreForm isSubmitting={isSubmitting} serverError={serverError} onCancel={onCancel} onSubmit={onSubmitStore} />
      )}
      {action === "area" && (
        <AddAreaForm
          parentOptions={storeRoots}
          isSubmitting={isSubmitting}
          serverError={serverError}
          onCancel={onCancel}
          onSubmit={onSubmitArea}
        />
      )}
      {action === "rack" && (
        <AddRackForm
          parentOptions={areaAndStoreOptions}
          isSubmitting={isSubmitting}
          serverError={serverError}
          onCancel={onCancel}
          onSubmit={onSubmitRack}
        />
      )}
      {action === "bin" && (
        <AddBinForm
          parentOptions={anyParentOptions}
          isSubmitting={isSubmitting}
          serverError={serverError}
          onCancel={onCancel}
          onSubmitSingle={onSubmitBinSingle}
          onSubmitBulk={onSubmitBinBulk}
        />
      )}
    </div>
  );
}

function NewStoreForm({
  isSubmitting, serverError, onCancel, onSubmit,
}: {
  isSubmitting: boolean;
  serverError?: string | null;
  onCancel: () => void;
  onSubmit: (payload: LocationCreate) => void;
}) {
  const { register, handleSubmit, formState: { errors } } = useForm<NewStoreFormValues>({
    resolver: zodResolver(newStoreFormSchema),
    defaultValues: { code: "", name: "" },
  });
  return (
    <form onSubmit={handleSubmit((v) => onSubmit(buildNewStorePayload(v)))} className="flex flex-col gap-4">
      <fieldset className="grid grid-cols-1 gap-4 rounded-xl border border-border-subtle bg-surface p-4 sm:grid-cols-2">
        <legend className="px-1 text-sm font-semibold text-ink">New Store</legend>
        <Field label="Code" error={errors.code?.message}>
          <input {...register("code")} className={inputClass} placeholder="MAIN-STORE" />
        </Field>
        <Field label="Name" error={errors.name?.message}>
          <input {...register("name")} className={inputClass} placeholder="Main Store" />
        </Field>
      </fieldset>
      {serverError && <p role="alert" className={errorClass}>{serverError}</p>}
      <div className="flex gap-3">
        <Button type="button" variant="secondary" onClick={onCancel} disabled={isSubmitting}>Cancel</Button>
        <Button type="submit" variant="primary" disabled={isSubmitting}>
          {isSubmitting ? "Creating…" : "Create Store"}
        </Button>
      </div>
    </form>
  );
}

function AddAreaForm({
  parentOptions, isSubmitting, serverError, onCancel, onSubmit,
}: {
  parentOptions: FlattenedStoreOption[];
  isSubmitting: boolean;
  serverError?: string | null;
  onCancel: () => void;
  onSubmit: (payload: LocationCreate) => void;
}) {
  const { register, handleSubmit, formState: { errors } } = useForm<AddAreaFormValues>({
    resolver: zodResolver(addAreaFormSchema),
    defaultValues: { parentLocationId: "", code: "", name: "" },
  });
  return (
    <form onSubmit={handleSubmit((v) => onSubmit(buildAddAreaPayload(v)))} className="flex flex-col gap-4">
      <fieldset className="grid grid-cols-1 gap-4 rounded-xl border border-border-subtle bg-surface p-4 sm:grid-cols-2">
        <legend className="px-1 text-sm font-semibold text-ink">Add Area</legend>
        <Field label="Store" error={errors.parentLocationId?.message}>
          <select {...register("parentLocationId")} className={inputClass}>
            <option value="">Select a Store…</option>
            {parentOptions.map((o) => <option key={o.id} value={o.id}>{o.label}</option>)}
          </select>
        </Field>
        <Field label="Code" error={errors.code?.message}>
          <input {...register("code")} className={inputClass} placeholder="SEED-AREA" />
        </Field>
        <Field label="Name" error={errors.name?.message}>
          <input {...register("name")} className={inputClass} placeholder="Seed Area" />
        </Field>
      </fieldset>
      {serverError && <p role="alert" className={errorClass}>{serverError}</p>}
      <div className="flex gap-3">
        <Button type="button" variant="secondary" onClick={onCancel} disabled={isSubmitting}>Cancel</Button>
        <Button type="submit" variant="primary" disabled={isSubmitting}>
          {isSubmitting ? "Creating…" : "Add Area"}
        </Button>
      </div>
    </form>
  );
}

function AddRackForm({
  parentOptions, isSubmitting, serverError, onCancel, onSubmit,
}: {
  parentOptions: FlattenedStoreOption[];
  isSubmitting: boolean;
  serverError?: string | null;
  onCancel: () => void;
  onSubmit: (payload: LocationCreate) => void;
}) {
  const { register, handleSubmit, formState: { errors } } = useForm<AddRackFormValues>({
    resolver: zodResolver(addRackFormSchema),
    defaultValues: { parentLocationId: "", code: "", name: "" },
  });
  return (
    <form onSubmit={handleSubmit((v) => onSubmit(buildAddRackPayload(v)))} className="flex flex-col gap-4">
      <fieldset className="grid grid-cols-1 gap-4 rounded-xl border border-border-subtle bg-surface p-4 sm:grid-cols-2">
        <legend className="px-1 text-sm font-semibold text-ink">Add Rack</legend>
        <Field label="Store or Area" error={errors.parentLocationId?.message}>
          <select {...register("parentLocationId")} className={inputClass}>
            <option value="">Select a parent…</option>
            {parentOptions.map((o) => <option key={o.id} value={o.id}>{o.label}</option>)}
          </select>
        </Field>
        <Field label="Code" error={errors.code?.message}>
          <input {...register("code")} className={inputClass} placeholder="RACK-01" />
        </Field>
        <Field label="Name" error={errors.name?.message}>
          <input {...register("name")} className={inputClass} placeholder="Rack 01" />
        </Field>
      </fieldset>
      {serverError && <p role="alert" className={errorClass}>{serverError}</p>}
      <div className="flex gap-3">
        <Button type="button" variant="secondary" onClick={onCancel} disabled={isSubmitting}>Cancel</Button>
        <Button type="submit" variant="primary" disabled={isSubmitting}>
          {isSubmitting ? "Creating…" : "Add Rack"}
        </Button>
      </div>
    </form>
  );
}

function AddBinForm({
  parentOptions, isSubmitting, serverError, onCancel, onSubmitSingle, onSubmitBulk,
}: {
  parentOptions: FlattenedStoreOption[];
  isSubmitting: boolean;
  serverError?: string | null;
  onCancel: () => void;
  onSubmitSingle: (payload: LocationCreate) => void;
  onSubmitBulk: (parentId: string, payload: LocationBulkChildrenCreate) => void;
}) {
  const { register, control, handleSubmit, formState: { errors } } = useForm<AddBinFormValues>({
    resolver: zodResolver(addBinFormSchema),
    defaultValues: DEFAULT_ADD_BIN_FORM_VALUES,
  });
  const mode = useWatch({ control, name: "mode" });

  function submit(values: AddBinFormValues) {
    if (values.mode === "single") {
      onSubmitSingle(buildAddBinSinglePayload(values));
    } else {
      onSubmitBulk(values.parentLocationId, buildAddBinBulkPayload(values));
    }
  }

  return (
    <form onSubmit={handleSubmit(submit)} className="flex flex-col gap-4">
      <fieldset className="grid grid-cols-1 gap-4 rounded-xl border border-border-subtle bg-surface p-4 sm:grid-cols-2">
        <legend className="px-1 text-sm font-semibold text-ink">Add Bin(s)</legend>
        <Field label="Store, Area, or Rack" error={errors.parentLocationId?.message}>
          <select {...register("parentLocationId")} className={inputClass}>
            <option value="">Select a parent…</option>
            {parentOptions.map((o) => <option key={o.id} value={o.id}>{o.label}</option>)}
          </select>
        </Field>
        <Field label="Mode">
          <select {...register("mode")} className={inputClass}>
            <option value="single">Single bin</option>
            <option value="bulk">Multiple bins (generated)</option>
          </select>
        </Field>
      </fieldset>

      {mode === "single" ? (
        <fieldset className="grid grid-cols-1 gap-4 rounded-xl border border-border-subtle bg-surface p-4 sm:grid-cols-2">
          <legend className="px-1 text-sm font-semibold text-ink">Bin</legend>
          <Field label="Code" error={errors.code?.message}>
            <input {...register("code")} className={inputClass} placeholder="BIN-001" />
          </Field>
          <Field label="Name" error={errors.name?.message}>
            <input {...register("name")} className={inputClass} placeholder="Bin 001" />
          </Field>
        </fieldset>
      ) : (
        <fieldset className="grid grid-cols-1 gap-4 rounded-xl border border-border-subtle bg-surface p-4 sm:grid-cols-2">
          <legend className="px-1 text-sm font-semibold text-ink">Generate bins</legend>
          <Field label="Code prefix" error={errors.codePrefix?.message}>
            <input {...register("codePrefix")} className={inputClass} placeholder="BIN-" />
          </Field>
          <Field label="Name template (optional)">
            <input {...register("nameTemplate")} className={inputClass} placeholder="Bin {n}" />
          </Field>
          <Field label="Start" error={errors.start?.message}>
            <input type="number" {...register("start", { valueAsNumber: true })} className={inputClass} />
          </Field>
          <Field label="End" error={errors.end?.message}>
            <input type="number" {...register("end", { valueAsNumber: true })} className={inputClass} />
          </Field>
          <Field label="Pad width" error={errors.padWidth?.message}>
            <input type="number" {...register("padWidth", { valueAsNumber: true })} className={inputClass} />
          </Field>
        </fieldset>
      )}

      {serverError && <p role="alert" className={errorClass}>{serverError}</p>}
      <div className="flex gap-3">
        <Button type="button" variant="secondary" onClick={onCancel} disabled={isSubmitting}>Cancel</Button>
        <Button type="submit" variant="primary" disabled={isSubmitting}>
          {isSubmitting ? "Creating…" : "Add Bin(s)"}
        </Button>
      </div>
    </form>
  );
}
