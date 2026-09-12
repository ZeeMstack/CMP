"use client";

import Link from "next/link";
import { useRef, useState } from "react";

import { EmptyState } from "@/components/EmptyState";
import { Button } from "@/components/ui/Button";
import type { GoodsReceiptCreate, GoodsReceiptLineIn, InventoryItemRead } from "@/lib/api/client";
import { AppError } from "@/lib/errors/adapter";
import { useInventoryItemPackaging, useInventoryItems, useSeedProfileForItem, useUoms } from "@/lib/query/hooks";

const inputClass =
  "min-h-10 w-full rounded-md border border-wl-border bg-wl-surface-raised px-3 text-sm text-wl-text focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-wl-focus";
const labelClass = "block text-xs font-medium text-wl-text-secondary";
const errorClass = "text-xs text-danger-700";

function Field({ label, error, children }: { label: string; error?: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1">
      <span className={labelClass}>{label}</span>
      {children}
      {error && <span className={errorClass}>{error}</span>}
    </label>
  );
}

let lineKeySeq = 0;
function nextLineKey(): string {
  lineKeySeq += 1;
  return `line-${lineKeySeq}`;
}

interface LineState {
  key: string;
  inventoryItemId: string;
  mode: "direct" | "packaging";
  enteredQuantity: string;
  enteredUomId: string;
  packagingId: string;
  packageCount: string;
  manufacturerName: string;
  manufacturerLotReference: string;
  manufacturingDate: string;
  expiryDate: string;
  seedLotCode: string;
}

function emptyLine(): LineState {
  return {
    key: nextLineKey(), inventoryItemId: "", mode: "direct", enteredQuantity: "", enteredUomId: "",
    packagingId: "", packageCount: "", manufacturerName: "", manufacturerLotReference: "", manufacturingDate: "",
    expiryDate: "", seedLotCode: "",
  };
}

/** Every field's validity, keyed by field name, non-empty message = error. */
type LineErrors = Partial<Record<keyof LineState, string>>;

function validateLine(line: LineState, item: InventoryItemRead | undefined): LineErrors {
  const errors: LineErrors = {};
  if (!line.inventoryItemId) {
    errors.inventoryItemId = "Select an item";
    return errors;
  }
  if (!item) return errors;

  if (line.mode === "direct") {
    const qty = Number(line.enteredQuantity);
    if (!line.enteredQuantity || Number.isNaN(qty) || qty <= 0) {
      errors.enteredQuantity = "Enter a quantity greater than zero";
    }
    if (!line.enteredUomId) errors.enteredUomId = "Select a unit";
  } else {
    if (!line.packagingId) errors.packagingId = "Select a packaging option";
    const count = Number(line.packageCount);
    if (!line.packageCount || !Number.isInteger(count) || count <= 0) {
      errors.packageCount = "Enter a package count greater than zero";
    }
  }

  if (item.lot_tracking_required) {
    if (line.manufacturerLotReference && !line.manufacturerName) {
      errors.manufacturerName = "Manufacturer name is required when a lot reference is entered";
    }
    if (item.expiry_tracking_required && !line.expiryDate) {
      errors.expiryDate = "Expiry date is required for this item";
    }
  }

  return errors;
}

/** Only renders seed-linking fields for an item that HAS Seed Details (an
 * `InventoryItemSeedProfile` exists) -- never offered generically, never
 * inferred from category (docs/domain/STORE_INVENTORY_MODEL.md §15). Its
 * own component so `useSeedProfileForItem` is called once per mounted
 * line, never conditionally inside a loop. */
function SeedLotField({
  itemId, value, onChange,
}: {
  itemId: string;
  value: string;
  onChange: (value: string) => void;
}) {
  const profileQuery = useSeedProfileForItem(itemId || undefined);
  if (!itemId || profileQuery.isLoading || !profileQuery.data) return null;
  return (
    <Field label="Seed Lot code (this item has Seed Details)">
      <input
        className={inputClass}
        value={value}
        placeholder="e.g. SL-2026-001"
        onChange={(e) => onChange(e.target.value)}
      />
      <span className="text-xs text-wl-text-tertiary">
        A Seed Lot will be linked to this receipt automatically.
      </span>
    </Field>
  );
}

/** Whether any optional lot field on this line already has a value -- used
 * to badge the "Lot details" toggle so a collapsed row never silently hides
 * data the operator already entered. */
function hasLotDetails(line: LineState): boolean {
  return Boolean(
    line.manufacturerName || line.manufacturerLotReference || line.manufacturingDate || line.expiryDate ||
      line.seedLotCode,
  );
}

/** PILOT-UX-001: one compact row per line -- item, quantity/packaging, and a
 * Remove action all inline. Optional lot fields (manufacturer, dates, seed
 * lot) stay collapsed behind "Lot details" so adding a line never grows into
 * another tall card. */
function LineRow({
  line, index, items, onChange, onRemove, canRemove, errors, lotDetailsOpen, onToggleLotDetails,
}: {
  line: LineState;
  index: number;
  items: InventoryItemRead[];
  onChange: (next: LineState) => void;
  onRemove: () => void;
  canRemove: boolean;
  errors: LineErrors;
  lotDetailsOpen: boolean;
  onToggleLotDetails: () => void;
}) {
  const item = items.find((i) => i.id === line.inventoryItemId);
  const packagingQuery = useInventoryItemPackaging({ status: "active" });
  const packagingOptions = (packagingQuery.data ?? []).filter((p) => p.inventory_item_id === line.inventoryItemId);
  const uomsQuery = useUoms();

  const selectedPackaging = packagingOptions.find((p) => p.id === line.packagingId);
  const packageCountNum = Number(line.packageCount);
  const previewBaseQuantity =
    selectedPackaging && Number.isInteger(packageCountNum) && packageCountNum > 0
      ? (Number(selectedPackaging.package_quantity) * packageCountNum).toFixed(3)
      : null;

  const baseUom = uomsQuery.data?.find((u) => u.id === item?.base_uom_id);
  const enteredUom = uomsQuery.data?.find((u) => u.id === line.enteredUomId);
  const isSameUom = item && line.enteredUomId && line.enteredUomId === item.base_uom_id;

  function update(patch: Partial<LineState>) {
    onChange({ ...line, ...patch });
  }

  const lotDetailsFilled = hasLotDetails(line);

  return (
    <div className="flex flex-col gap-3 rounded-lg border border-wl-border bg-wl-surface-raised p-3">
      <div className="flex flex-wrap items-end gap-3">
        <div className="w-8 shrink-0 pb-2.5 text-xs font-medium text-wl-text-tertiary">{index + 1}</div>

        <div className="min-w-[10rem] flex-1">
          <Field label="Inventory Item" error={errors.inventoryItemId}>
            <select
              className={inputClass}
              value={line.inventoryItemId}
              onChange={(e) =>
                update({
                  inventoryItemId: e.target.value, packagingId: "", packageCount: "", enteredQuantity: "",
                  enteredUomId: "", manufacturerName: "", manufacturerLotReference: "", manufacturingDate: "",
                  expiryDate: "", seedLotCode: "",
                })
              }
            >
              <option value="">Select an item…</option>
              {items.map((i) => (
                <option key={i.id} value={i.id}>{i.name}</option>
              ))}
            </select>
          </Field>
        </div>

        {item && (
          <>
            <div className="flex shrink-0 flex-col gap-1">
              <span className={labelClass}>Mode</span>
              <div className="flex overflow-hidden rounded-md border border-wl-border">
                <button
                  type="button"
                  onClick={() => update({ mode: "direct", packagingId: "", packageCount: "" })}
                  className={`min-h-10 px-2.5 text-xs font-medium ${
                    line.mode === "direct" ? "bg-wl-brand text-wl-text-on-brand" : "bg-wl-surface-raised text-wl-text-secondary"
                  }`}
                >
                  Qty
                </button>
                <button
                  type="button"
                  onClick={() => update({ mode: "packaging", enteredQuantity: "", enteredUomId: "" })}
                  className={`min-h-10 px-2.5 text-xs font-medium ${
                    line.mode === "packaging" ? "bg-wl-brand text-wl-text-on-brand" : "bg-wl-surface-raised text-wl-text-secondary"
                  }`}
                >
                  Packaging
                </button>
              </div>
            </div>

            {line.mode === "direct" ? (
              <>
                <div className="w-28 shrink-0">
                  <Field label="Quantity" error={errors.enteredQuantity}>
                    <input
                      className={inputClass}
                      type="number"
                      min="0"
                      step="any"
                      value={line.enteredQuantity}
                      onChange={(e) => update({ enteredQuantity: e.target.value })}
                    />
                  </Field>
                </div>
                <div className="w-24 shrink-0">
                  <Field label="Unit" error={errors.enteredUomId}>
                    <select
                      className={inputClass}
                      value={line.enteredUomId}
                      onChange={(e) => update({ enteredUomId: e.target.value })}
                    >
                      <option value="">Select…</option>
                      {(uomsQuery.data ?? []).map((u) => (
                        <option key={u.id} value={u.id}>{u.code}</option>
                      ))}
                    </select>
                  </Field>
                </div>
              </>
            ) : (
              <>
                <div className="min-w-[9rem] flex-1">
                  <Field label="Packaging Option" error={errors.packagingId}>
                    <select
                      className={inputClass}
                      value={line.packagingId}
                      onChange={(e) => update({ packagingId: e.target.value })}
                    >
                      <option value="">Select…</option>
                      {packagingOptions.map((p) => (
                        <option key={p.id} value={p.id}>{p.display_name}</option>
                      ))}
                    </select>
                  </Field>
                </div>
                <div className="w-28 shrink-0">
                  <Field label="Number of packages" error={errors.packageCount}>
                    <input
                      className={inputClass}
                      type="number"
                      min="1"
                      step="1"
                      value={line.packageCount}
                      onChange={(e) => update({ packageCount: e.target.value })}
                    />
                  </Field>
                </div>
              </>
            )}

            {item.lot_tracking_required && (
              <div className="shrink-0 pb-2.5">
                <button
                  type="button"
                  onClick={onToggleLotDetails}
                  className="min-h-10 whitespace-nowrap rounded-md border border-wl-border px-2.5 text-xs font-medium text-wl-text-secondary hover:bg-wl-surface-hover"
                >
                  Lot details{lotDetailsFilled ? " ✓" : ""} {lotDetailsOpen ? "▲" : "▼"}
                </button>
              </div>
            )}
          </>
        )}

        <div className="ml-auto shrink-0 pb-2.5">
          {canRemove && (
            <button type="button" className="text-xs font-medium text-danger-700 hover:underline" onClick={onRemove}>
              Remove
            </button>
          )}
        </div>
      </div>

      {item && line.mode === "direct" && line.enteredUomId && baseUom && enteredUom && (
        <p className="text-xs text-wl-text-tertiary">
          {isSameUom
            ? `Recorded as entered (${baseUom.code} is this item's base unit).`
            : `Will be converted automatically to this item's base unit (${baseUom.code}).`}
        </p>
      )}
      {item && line.mode === "packaging" && previewBaseQuantity && baseUom && (
        <p className="text-xs text-wl-text-tertiary">
          Normalized quantity: {previewBaseQuantity} {baseUom.code}
        </p>
      )}

      {item?.lot_tracking_required && lotDetailsOpen && (
        <div className="grid grid-cols-2 gap-3 border-t border-wl-border pt-3">
          <Field label="Manufacturer" error={errors.manufacturerName}>
            <input
              className={inputClass}
              value={line.manufacturerName}
              onChange={(e) => update({ manufacturerName: e.target.value })}
            />
          </Field>
          <Field label="Manufacturer Lot Reference">
            <input
              className={inputClass}
              value={line.manufacturerLotReference}
              onChange={(e) => update({ manufacturerLotReference: e.target.value })}
            />
          </Field>
          <Field label="Manufacturing Date">
            <input
              className={inputClass}
              type="date"
              value={line.manufacturingDate}
              onChange={(e) => update({ manufacturingDate: e.target.value })}
            />
          </Field>
          <Field label={`Expiry Date${item.expiry_tracking_required ? " (required)" : ""}`} error={errors.expiryDate}>
            <input
              className={inputClass}
              type="date"
              value={line.expiryDate}
              onChange={(e) => update({ expiryDate: e.target.value })}
            />
          </Field>
          <div className="col-span-2">
            <SeedLotField
              itemId={line.inventoryItemId}
              value={line.seedLotCode}
              onChange={(v) => update({ seedLotCode: v })}
            />
          </div>
        </div>
      )}
    </div>
  );
}

/** STORE-INV-002A.2: "Receive Goods" -- one client-side multi-line form over
 * `.1`'s already-shipped `record_goods_receipt` command. No server Draft:
 * enter receipt details -> add lines -> review inline -> Record Receipt. */
export function ReceiveGoodsForm({
  onSubmit, isSubmitting, serverError,
}: {
  onSubmit: (payload: GoodsReceiptCreate) => void;
  isSubmitting: boolean;
  serverError?: AppError | null;
}) {
  const itemsQuery = useInventoryItems({ status: "active" });
  const items = itemsQuery.data ?? [];

  const [receivedDate, setReceivedDate] = useState(() => new Date().toISOString().slice(0, 10));
  const [receivedTime, setReceivedTime] = useState(() => new Date().toISOString().slice(11, 16));
  const [supplierName, setSupplierName] = useState("");
  const [notes, setNotes] = useState("");
  const [lines, setLines] = useState<LineState[]>([emptyLine()]);
  const [attempted, setAttempted] = useState(false);
  const [clientCommandId, setClientCommandId] = useState(() => crypto.randomUUID());
  const lastFingerprintRef = useRef<string | null>(null);
  // PILOT-UX-001: which lines have their optional Lot details expanded --
  // collapsed by default per line, matching progressive disclosure.
  const [openLotDetails, setOpenLotDetails] = useState<Set<string>>(new Set());

  const lineErrors = lines.map((line) => validateLine(line, items.find((i) => i.id === line.inventoryItemId)));
  const hasErrors = lineErrors.some((e) => Object.keys(e).length > 0);
  const isValid = lines.length > 0 && !hasErrors;

  function buildPayload(): GoodsReceiptCreate {
    const receivedAt = new Date(`${receivedDate}T${receivedTime}:00`).toISOString();
    const payloadLines: GoodsReceiptLineIn[] = lines.map((line) => {
      const item = items.find((i) => i.id === line.inventoryItemId);
      const base: GoodsReceiptLineIn = {
        inventory_item_id: line.inventoryItemId,
        entered_quantity: line.mode === "direct" ? Number(line.enteredQuantity) : null,
        entered_uom_id: line.mode === "direct" ? line.enteredUomId || null : null,
        packaging_id: line.mode === "packaging" ? line.packagingId || null : null,
        package_count: line.mode === "packaging" ? Number(line.packageCount) : null,
        manufacturer_name: item?.lot_tracking_required && line.manufacturerName ? line.manufacturerName : null,
        manufacturer_lot_reference:
          item?.lot_tracking_required && line.manufacturerLotReference ? line.manufacturerLotReference : null,
        manufacturing_date: item?.lot_tracking_required && line.manufacturingDate ? line.manufacturingDate : null,
        expiry_date: item?.lot_tracking_required && line.expiryDate ? line.expiryDate : null,
        seed_crop_id: null,
        seed_variety_id: null,
        seed_lot_code: null,
        external_line_id: null,
      };
      return base;
    });
    return {
      client_command_id: clientCommandId, received_at: receivedAt, supplier_name: supplierName.trim() || null,
      external_system: null, external_document_id: null, notes: notes.trim() || null, lines: payloadLines,
    };
  }

  function handleSubmit() {
    setAttempted(true);
    if (!isValid) {
      // PILOT-UX-003: a required/invalid Lot-details field (Manufacturer,
      // Expiry Date) must never fail validation silently inside a still-
      // collapsed row -- auto-reveal exactly the rows whose error actually
      // lives in that collapsed section, without touching any row the
      // operator has not opened for an unrelated reason.
      setOpenLotDetails((prev) => {
        const next = new Set(prev);
        lines.forEach((line, index) => {
          const err = lineErrors[index];
          if (err.manufacturerName || err.expiryDate) next.add(line.key);
        });
        return next;
      });
      return;
    }
    const payload = buildPayload();
    const fingerprint = JSON.stringify(payload.lines) + payload.received_at + (payload.supplier_name ?? "");
    let idToUse = clientCommandId;
    if (lastFingerprintRef.current !== null && lastFingerprintRef.current !== fingerprint) {
      idToUse = crypto.randomUUID();
      setClientCommandId(idToUse);
    }
    lastFingerprintRef.current = fingerprint;
    onSubmit({ ...payload, client_command_id: idToUse });
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="grid grid-cols-1 gap-3 rounded-xl border border-wl-border bg-wl-surface-raised p-4 sm:grid-cols-3">
        <Field label="Received date">
          <input className={inputClass} type="date" value={receivedDate} onChange={(e) => setReceivedDate(e.target.value)} />
        </Field>
        <Field label="Received time">
          <input className={inputClass} type="time" value={receivedTime} onChange={(e) => setReceivedTime(e.target.value)} />
        </Field>
        <Field label="Supplier / distributor (optional)">
          <input className={inputClass} value={supplierName} onChange={(e) => setSupplierName(e.target.value)} />
        </Field>
        <div className="sm:col-span-3">
          <Field label="Notes (optional)">
            <input className={inputClass} value={notes} onChange={(e) => setNotes(e.target.value)} />
          </Field>
        </div>
      </div>

      {itemsQuery.isSuccess && items.length === 0 ? (
        <EmptyState
          title="No inventory items are set up yet"
          description="Register at least one inventory item before receiving goods."
          action={
            <Link
              href="/inventory-items"
              className="inline-flex min-h-11 items-center gap-1.5 rounded-md border border-wl-border bg-wl-surface-raised px-3 text-sm font-medium text-wl-text hover:bg-wl-surface-hover focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-wl-focus"
            >
              Set up Inventory Items
            </Link>
          }
        />
      ) : (
        <>
          {lines.map((line, index) => (
            <LineRow
              key={line.key}
              line={line}
              index={index}
              items={items}
              errors={attempted ? lineErrors[index] : {}}
              canRemove={lines.length > 1}
              lotDetailsOpen={openLotDetails.has(line.key)}
              onToggleLotDetails={() =>
                setOpenLotDetails((prev) => {
                  const next = new Set(prev);
                  if (next.has(line.key)) next.delete(line.key);
                  else next.add(line.key);
                  return next;
                })
              }
              onChange={(next) => setLines((prev) => prev.map((l) => (l.key === line.key ? next : l)))}
              onRemove={() => setLines((prev) => prev.filter((l) => l.key !== line.key))}
            />
          ))}

          <Button type="button" variant="secondary" className="self-start" onClick={() => setLines((prev) => [...prev, emptyLine()])}>
            Add line
          </Button>
        </>
      )}

      {serverError && (
        <div className="rounded-md border border-wl-border-strong bg-wl-flag-bg p-3 text-sm text-wl-flag-fg">
          {serverError.message}
        </div>
      )}

      {attempted && hasErrors && (
        <p className="text-sm text-danger-700">Fix the highlighted fields before recording this receipt.</p>
      )}

      <Button type="button" variant="primary" className="self-start" disabled={isSubmitting} onClick={handleSubmit}>
        {isSubmitting ? "Recording…" : "Record Receipt"}
      </Button>
    </div>
  );
}
