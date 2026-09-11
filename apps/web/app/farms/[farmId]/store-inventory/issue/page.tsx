"use client";

import { useParams } from "next/navigation";
import { useState } from "react";

import { Breadcrumbs } from "@/components/Breadcrumbs";
import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/components/ui/Button";
import { Tabs } from "@/components/ui/Tabs";
import type {
  InventoryReservationLineRead, InventoryReservationRead, IssuableSourceRead, OutstandingIssuedMaterialRowRead,
} from "@/lib/api/client";
import { AppError } from "@/lib/errors/adapter";
import { activeBinsWithPaths } from "@/lib/locations/bins";
import {
  useCreateInventoryReservation,
  useInventoryItems,
  useInventoryReservations,
  useIssuableSources,
  useLocationsTree,
  useOutstandingIssuedMaterial,
  useRecordInventoryConsumption,
  useRecordInventoryIssue,
  useRecordInventoryReturn,
  useRecordInventoryScrap,
  useReleaseInventoryReservationLine,
  useUoms,
} from "@/lib/query/hooks";

const inputClass =
  "min-h-9 w-full rounded-md border border-wl-border bg-wl-surface-raised px-2 text-xs text-wl-text focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-wl-focus";
const labelClass = "block text-[11px] font-medium text-wl-text-secondary";

function asAppError(error: unknown): AppError {
  return error instanceof AppError ? error : new AppError("server_error", "Something went wrong. Please try again.");
}

function nowIso(): string {
  return new Date().toISOString();
}

function useItemOptions() {
  const itemsQuery = useInventoryItems({ status: "active" });
  const uomsQuery = useUoms();
  const items = itemsQuery.data ?? [];
  const uomsById = new Map((uomsQuery.data ?? []).map((u) => [u.id, u.code]));
  return { items, uomsById, isLoading: itemsQuery.isLoading || uomsQuery.isLoading };
}

function formatQty(value: string, uomCode: string | undefined): string {
  if (!uomCode) return value;
  return `${value} ${uomCode}`;
}

// --- ISSUE NOW ---------------------------------------------------------------

interface DirectLine {
  key: string;
  itemId: string;
  sourceKey: string; // `${cohortId}|${binId}`
  quantity: string;
}

function SourcePicker({
  farmId, itemId, sourceKey, onChange,
}: {
  farmId: string;
  itemId: string;
  sourceKey: string;
  onChange: (sourceKey: string) => void;
}) {
  const sourcesQuery = useIssuableSources(farmId, itemId || undefined);
  const sources = sourcesQuery.data ?? [];

  if (sourcesQuery.isLoading) return <span className="text-[11px] text-wl-text-tertiary">Loading…</span>;
  if (!itemId) return <span className="text-[11px] text-wl-text-tertiary">Pick an item first</span>;
  if (sources.length === 0) return <span className="text-[11px] text-danger-700">No usable stock in a Bin</span>;

  if (sources.length === 1) {
    const s = sources[0];
    const key = `${s.inventory_quantity_cohort_id}|${s.source_location_id}`;
    if (sourceKey !== key) onChange(key);
    return (
      <span className="text-[11px] text-wl-text">
        {s.lot_label ?? "—"} @ {s.bin_label}
      </span>
    );
  }

  return (
    <select className={inputClass} value={sourceKey} onChange={(e) => onChange(e.target.value)}>
      <option value="">Select source…</option>
      {sources.map((s: IssuableSourceRead) => {
        const key = `${s.inventory_quantity_cohort_id}|${s.source_location_id}`;
        return (
          <option key={key} value={key}>
            {s.lot_label ?? "—"} @ {s.bin_label} ({s.balance})
          </option>
        );
      })}
    </select>
  );
}

function IssueNowPanel({ farmId }: { farmId: string }) {
  const { items, uomsById, isLoading } = useItemOptions();
  const [purpose, setPurpose] = useState("");
  const [rows, setRows] = useState<DirectLine[]>([
    { key: crypto.randomUUID(), itemId: "", sourceKey: "", quantity: "" },
  ]);
  const [error, setError] = useState<AppError | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const issueMutation = useRecordInventoryIssue();

  const updateRow = (key: string, patch: Partial<DirectLine>) =>
    setRows((prev) => prev.map((r) => (r.key === key ? { ...r, ...patch } : r)));

  const canSubmit =
    purpose.trim().length > 0 &&
    rows.length > 0 &&
    rows.every((r) => r.itemId && r.sourceKey && r.quantity && Number(r.quantity) > 0);

  return (
    <div className="flex flex-col gap-3">
      <label className="flex flex-col gap-1">
        <span className={labelClass}>Purpose</span>
        <input
          className={inputClass}
          value={purpose}
          onChange={(e) => setPurpose(e.target.value)}
          placeholder="e.g. Fertigation prep for GH-01"
        />
      </label>

      <div className="overflow-x-auto rounded-xl border border-wl-border bg-wl-surface-raised">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-wl-border text-left text-wl-text-tertiary">
              <th className="p-2 font-medium">Item</th>
              <th className="p-2 font-medium">Source (Lot @ Bin)</th>
              <th className="p-2 font-medium">Qty</th>
              <th className="p-2 font-medium">UOM</th>
              <th className="p-2" />
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => {
              const item = items.find((i) => i.id === row.itemId);
              const uomCode = item ? uomsById.get(item.base_uom_id) : undefined;
              return (
                <tr key={row.key} className="border-b border-wl-border last:border-0">
                  <td className="p-2">
                    <select
                      className={inputClass}
                      value={row.itemId}
                      onChange={(e) => updateRow(row.key, { itemId: e.target.value, sourceKey: "" })}
                    >
                      <option value="">Select item…</option>
                      {items.map((i) => (
                        <option key={i.id} value={i.id}>{i.name}</option>
                      ))}
                    </select>
                  </td>
                  <td className="p-2">
                    {row.itemId ? (
                      <SourcePicker
                        farmId={farmId} itemId={row.itemId} sourceKey={row.sourceKey}
                        onChange={(sourceKey) => updateRow(row.key, { sourceKey })}
                      />
                    ) : (
                      <span className="text-[11px] text-wl-text-tertiary">—</span>
                    )}
                  </td>
                  <td className="p-2">
                    <input
                      className={inputClass}
                      type="number"
                      min="0"
                      step="any"
                      value={row.quantity}
                      onChange={(e) => updateRow(row.key, { quantity: e.target.value })}
                    />
                  </td>
                  <td className="p-2 text-wl-text-tertiary">{uomCode ?? "—"}</td>
                  <td className="p-2 text-right">
                    {rows.length > 1 && (
                      <button
                        type="button"
                        className="text-wl-text-tertiary hover:text-danger-700"
                        onClick={() => setRows((prev) => prev.filter((r) => r.key !== row.key))}
                        aria-label="Remove line"
                      >
                        ✕
                      </button>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <div>
        <button
          type="button"
          className="text-xs font-medium text-wl-brand hover:underline"
          onClick={() => setRows((prev) => [...prev, { key: crypto.randomUUID(), itemId: "", sourceKey: "", quantity: "" }])}
        >
          + Add line
        </button>
      </div>

      {error && <p className="rounded-md border border-wl-border-strong bg-wl-flag-bg p-2 text-xs text-wl-flag-fg">{error.message}</p>}
      {success && (
        <p className="rounded-md border border-wl-border-strong bg-wl-grow-bg p-2 text-xs text-wl-grow-fg">{success}</p>
      )}

      <div>
        <Button
          type="button"
          variant="primary"
          disabled={!canSubmit || isLoading || issueMutation.isPending}
          onClick={() => {
            setError(null);
            setSuccess(null);
            issueMutation.mutate(
              {
                farmId,
                payload: {
                  client_command_id: crypto.randomUUID(),
                  purpose: purpose.trim(),
                  effective_time: nowIso(),
                  reservation_id: null,
                  lines: rows.map((r) => {
                    const [cohortId, binId] = r.sourceKey.split("|");
                    return {
                      inventory_item_id: r.itemId,
                      inventory_quantity_cohort_id: cohortId,
                      source_location_id: binId,
                      quantity: r.quantity,
                      reservation_line_id: null,
                    };
                  }),
                },
              },
              {
                onSuccess: (issue) => {
                  setSuccess(`Issued as ${issue.code}.`);
                  setPurpose("");
                  setRows([{ key: crypto.randomUUID(), itemId: "", sourceKey: "", quantity: "" }]);
                },
                onError: (err) => setError(asAppError(err)),
              },
            );
          }}
        >
          {issueMutation.isPending ? "Issuing…" : "Issue material"}
        </Button>
      </div>
    </div>
  );
}

// --- RESERVATIONS --------------------------------------------------------------

interface NewReservationLine {
  key: string;
  itemId: string;
  quantity: string;
}

function CreateReservationForm({ farmId, onDone }: { farmId: string; onDone: () => void }) {
  const { items, uomsById } = useItemOptions();
  const [purpose, setPurpose] = useState("");
  const [lines, setLines] = useState<NewReservationLine[]>([{ key: crypto.randomUUID(), itemId: "", quantity: "" }]);
  const [error, setError] = useState<AppError | null>(null);
  const createMutation = useCreateInventoryReservation();

  const updateLine = (key: string, patch: Partial<NewReservationLine>) =>
    setLines((prev) => prev.map((l) => (l.key === key ? { ...l, ...patch } : l)));

  const canSubmit =
    purpose.trim().length > 0 && lines.every((l) => l.itemId && l.quantity && Number(l.quantity) > 0);

  return (
    <div className="flex flex-col gap-2 rounded-lg border border-wl-border bg-wl-surface-raised p-3">
      <label className="flex flex-col gap-1">
        <span className={labelClass}>Purpose</span>
        <input className={inputClass} value={purpose} onChange={(e) => setPurpose(e.target.value)} placeholder="e.g. Seeding WO-1" />
      </label>

      {lines.map((line) => {
        const item = items.find((i) => i.id === line.itemId);
        const uomCode = item ? uomsById.get(item.base_uom_id) : undefined;
        return (
          <div key={line.key} className="grid grid-cols-1 gap-2 sm:grid-cols-[1fr_auto_auto_auto]">
            <select className={inputClass} value={line.itemId} onChange={(e) => updateLine(line.key, { itemId: e.target.value })}>
              <option value="">Select item…</option>
              {items.map((i) => (
                <option key={i.id} value={i.id}>{i.name}</option>
              ))}
            </select>
            <input
              className={inputClass}
              type="number"
              min="0"
              step="any"
              placeholder="Qty"
              value={line.quantity}
              onChange={(e) => updateLine(line.key, { quantity: e.target.value })}
            />
            <span className="flex items-center text-[11px] text-wl-text-tertiary">{uomCode ?? "—"}</span>
            {lines.length > 1 ? (
              <button
                type="button"
                className="text-wl-text-tertiary hover:text-danger-700"
                onClick={() => setLines((prev) => prev.filter((l) => l.key !== line.key))}
              >
                ✕
              </button>
            ) : (
              <span />
            )}
          </div>
        );
      })}

      <div>
        <button
          type="button"
          className="text-xs font-medium text-wl-brand hover:underline"
          onClick={() => setLines((prev) => [...prev, { key: crypto.randomUUID(), itemId: "", quantity: "" }])}
        >
          + Add item
        </button>
      </div>

      {error && <p className="rounded-md border border-wl-border-strong bg-wl-flag-bg p-2 text-xs text-wl-flag-fg">{error.message}</p>}

      <div className="flex gap-2">
        <Button
          type="button"
          variant="primary"
          disabled={!canSubmit || createMutation.isPending}
          onClick={() => {
            setError(null);
            createMutation.mutate(
              {
                farmId,
                payload: {
                  client_command_id: crypto.randomUUID(),
                  purpose: purpose.trim(),
                  effective_time: nowIso(),
                  lines: lines.map((l) => ({ inventory_item_id: l.itemId, quantity: l.quantity })),
                },
              },
              { onSuccess: onDone, onError: (err) => setError(asAppError(err)) },
            );
          }}
        >
          {createMutation.isPending ? "Reserving…" : "Reserve"}
        </Button>
        <Button type="button" variant="secondary" onClick={onDone} disabled={createMutation.isPending}>
          Cancel
        </Button>
      </div>
    </div>
  );
}

function ReservationLineDrawerRow({
  farmId, reservation, line,
}: {
  farmId: string;
  reservation: InventoryReservationRead;
  line: InventoryReservationLineRead;
}) {
  const { items, uomsById } = useItemOptions();
  const item = items.find((i) => i.id === line.inventory_item_id);
  const uomCode = item ? uomsById.get(item.base_uom_id) : undefined;

  const [issueQty, setIssueQty] = useState("");
  const [sourceKey, setSourceKey] = useState("");
  const [releaseQty, setReleaseQty] = useState("");
  const [error, setError] = useState<AppError | null>(null);

  const issueMutation = useRecordInventoryIssue();
  const releaseMutation = useReleaseInventoryReservationLine();

  return (
    <div className="flex flex-col gap-2 border-t border-wl-border/60 p-2">
      <div className="flex flex-wrap items-center justify-between gap-2 text-[11px]">
        <span className="font-medium text-wl-text">
          {item?.name ?? line.inventory_item_id} — {formatQty(line.remaining_quantity_base, uomCode)} remaining of{" "}
          {formatQty(line.requested_quantity_base, uomCode)}
        </span>
        {line.blocked_by_quality && (
          <span className="rounded bg-amber-100 px-1.5 py-0.5 font-medium text-amber-800">
            Blocked — insufficient usable Store stock
          </span>
        )}
      </div>

      {error && <p className="rounded-md border border-wl-border-strong bg-wl-flag-bg p-2 text-[11px] text-wl-flag-fg">{error.message}</p>}

      {Number(line.remaining_quantity_base) > 0 && (
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-[1fr_auto_auto]">
          <SourcePicker farmId={farmId} itemId={line.inventory_item_id} sourceKey={sourceKey} onChange={setSourceKey} />
          <input
            className={inputClass}
            type="number"
            min="0"
            step="any"
            placeholder="Qty to issue"
            value={issueQty}
            onChange={(e) => setIssueQty(e.target.value)}
          />
          <Button
            type="button"
            variant="primary"
            disabled={!sourceKey || !issueQty || Number(issueQty) <= 0 || issueMutation.isPending}
            onClick={() => {
              setError(null);
              const [cohortId, binId] = sourceKey.split("|");
              issueMutation.mutate(
                {
                  farmId,
                  payload: {
                    client_command_id: crypto.randomUUID(),
                    purpose: `Issue against ${reservation.code}`,
                    effective_time: nowIso(),
                    reservation_id: reservation.id,
                    lines: [
                      {
                        inventory_item_id: line.inventory_item_id, inventory_quantity_cohort_id: cohortId,
                        source_location_id: binId, quantity: issueQty, reservation_line_id: line.id,
                      },
                    ],
                  },
                },
                { onSuccess: () => setIssueQty(""), onError: (err) => setError(asAppError(err)) },
              );
            }}
          >
            {issueMutation.isPending ? "Issuing…" : "Issue"}
          </Button>

          <input
            className={inputClass}
            type="number"
            min="0"
            step="any"
            placeholder="Qty to release"
            value={releaseQty}
            onChange={(e) => setReleaseQty(e.target.value)}
          />
          <span />
          <Button
            type="button"
            variant="secondary"
            disabled={!releaseQty || Number(releaseQty) <= 0 || releaseMutation.isPending}
            onClick={() => {
              setError(null);
              releaseMutation.mutate(
                {
                  farmId, lineId: line.id,
                  payload: { client_command_id: crypto.randomUUID(), quantity: releaseQty, effective_time: nowIso(), reason: null },
                },
                { onSuccess: () => setReleaseQty(""), onError: (err) => setError(asAppError(err)) },
              );
            }}
          >
            {releaseMutation.isPending ? "Releasing…" : "Release"}
          </Button>
        </div>
      )}
    </div>
  );
}

function ReservationRow({ farmId, reservation }: { farmId: string; reservation: InventoryReservationRead }) {
  const [expanded, setExpanded] = useState(false);
  const { items, uomsById } = useItemOptions();

  const totalRequested = reservation.lines.reduce((sum, l) => sum + Number(l.requested_quantity_base), 0);
  const totalRemaining = reservation.lines.reduce((sum, l) => sum + Number(l.remaining_quantity_base), 0);
  const anyBlocked = reservation.lines.some((l) => l.blocked_by_quality);
  const itemNames = reservation.lines
    .map((l) => items.find((i) => i.id === l.inventory_item_id)?.name ?? l.inventory_item_id)
    .join(", ");
  const status = totalRemaining === 0 ? "Fulfilled" : anyBlocked ? "Blocked — insufficient usable Store stock" : "Active";
  const firstUom = items.find((i) => i.id === reservation.lines[0]?.inventory_item_id);
  const uomCode = firstUom ? uomsById.get(firstUom.base_uom_id) : undefined;

  return (
    <li className="rounded-xl border border-wl-border bg-wl-surface-raised">
      <div className="flex flex-wrap items-center justify-between gap-2 p-3">
        <div className="flex flex-col gap-0.5">
          <span className="text-xs font-medium text-wl-text">{reservation.code} · {reservation.purpose}</span>
          <span className="text-[11px] text-wl-text-tertiary">{itemNames}</span>
        </div>
        <div className="flex items-center gap-3 text-[11px] text-wl-text-secondary">
          <span>Reserved: {reservation.lines.length === 1 ? formatQty(String(totalRequested), uomCode) : totalRequested}</span>
          <span>Remaining: {reservation.lines.length === 1 ? formatQty(String(totalRemaining), uomCode) : totalRemaining}</span>
          <span className={anyBlocked ? "font-medium text-amber-700" : "font-medium text-wl-text"}>{status}</span>
          <button type="button" className="font-medium text-wl-brand hover:underline" onClick={() => setExpanded((v) => !v)}>
            {expanded ? "Hide" : "Issue / Release"}
          </button>
        </div>
      </div>
      {expanded && (
        <div className="flex flex-col">
          {reservation.lines.map((line) => (
            <ReservationLineDrawerRow key={line.id} farmId={farmId} reservation={reservation} line={line} />
          ))}
        </div>
      )}
    </li>
  );
}

function ReservationsPanel({ farmId }: { farmId: string }) {
  const reservationsQuery = useInventoryReservations(farmId);
  const [creating, setCreating] = useState(false);
  const reservations = reservationsQuery.data ?? [];

  return (
    <div className="flex flex-col gap-3">
      {!creating && (
        <div>
          <Button type="button" variant="primary" onClick={() => setCreating(true)}>
            + New reservation
          </Button>
        </div>
      )}
      {creating && <CreateReservationForm farmId={farmId} onDone={() => setCreating(false)} />}

      {reservationsQuery.isLoading ? (
        <p className="text-sm text-wl-text-secondary">Loading…</p>
      ) : reservations.length === 0 ? (
        <p className="text-sm text-wl-text">No reservations yet.</p>
      ) : (
        <ul className="flex flex-col gap-2">
          {reservations.map((r) => (
            <ReservationRow key={r.id} farmId={farmId} reservation={r} />
          ))}
        </ul>
      )}
    </div>
  );
}

// --- ISSUED MATERIAL -------------------------------------------------------------

type IssuedMaterialAction = "consume" | "return" | "scrap" | null;

function ConsumeInlinePanel({ farmId, row, onDone }: { farmId: string; row: OutstandingIssuedMaterialRowRead; onDone: () => void }) {
  const [quantity, setQuantity] = useState("");
  const [error, setError] = useState<AppError | null>(null);
  const consumeMutation = useRecordInventoryConsumption();
  const { uomsById } = useItemOptions();
  const uomCode = uomsById.get(row.base_uom_id);

  return (
    <div className="flex flex-wrap items-end gap-2 rounded-lg border border-wl-border bg-wl-surface-raised p-2">
      <label className="flex flex-col gap-1">
        <span className={labelClass}>Qty {uomCode ? `(${uomCode})` : ""}</span>
        <input
          className={inputClass} type="number" min="0" step="any" value={quantity}
          onChange={(e) => setQuantity(e.target.value)}
        />
      </label>
      {error && <p className="text-[11px] text-danger-700">{error.message}</p>}
      <Button
        type="button" variant="primary"
        disabled={!quantity || Number(quantity) <= 0 || consumeMutation.isPending}
        onClick={() => {
          setError(null);
          consumeMutation.mutate(
            { farmId, payload: { client_command_id: crypto.randomUUID(), issue_line_id: row.issue_line_id, quantity, effective_time: nowIso() } },
            { onSuccess: onDone, onError: (err) => setError(asAppError(err)) },
          );
        }}
      >
        {consumeMutation.isPending ? "Recording…" : "Confirm consumption"}
      </Button>
      <Button type="button" variant="secondary" onClick={onDone} disabled={consumeMutation.isPending}>Cancel</Button>
    </div>
  );
}

function ReturnInlinePanel({
  farmId, row, activeBins, onDone,
}: { farmId: string; row: OutstandingIssuedMaterialRowRead; activeBins: { id: string; label: string }[]; onDone: () => void }) {
  const [quantity, setQuantity] = useState("");
  const [binId, setBinId] = useState(activeBins[0]?.id ?? "");
  const [error, setError] = useState<AppError | null>(null);
  const returnMutation = useRecordInventoryReturn();
  const { uomsById } = useItemOptions();
  const uomCode = uomsById.get(row.base_uom_id);

  return (
    <div className="flex flex-wrap items-end gap-2 rounded-lg border border-wl-border bg-wl-surface-raised p-2">
      <label className="flex flex-col gap-1">
        <span className={labelClass}>Qty {uomCode ? `(${uomCode})` : ""}</span>
        <input
          className={inputClass} type="number" min="0" step="any" value={quantity}
          onChange={(e) => setQuantity(e.target.value)}
        />
      </label>
      <label className="flex flex-col gap-1">
        <span className={labelClass}>Bin</span>
        <select className={inputClass} value={binId} onChange={(e) => setBinId(e.target.value)}>
          {activeBins.map((b) => (
            <option key={b.id} value={b.id}>{b.label}</option>
          ))}
        </select>
      </label>
      {error && <p className="text-[11px] text-danger-700">{error.message}</p>}
      <Button
        type="button" variant="primary"
        disabled={!quantity || Number(quantity) <= 0 || !binId || returnMutation.isPending}
        onClick={() => {
          setError(null);
          returnMutation.mutate(
            {
              farmId,
              payload: {
                client_command_id: crypto.randomUUID(), issue_line_id: row.issue_line_id,
                destination_location_id: binId, quantity, effective_time: nowIso(),
              },
            },
            { onSuccess: onDone, onError: (err) => setError(asAppError(err)) },
          );
        }}
      >
        {returnMutation.isPending ? "Recording…" : "Confirm return"}
      </Button>
      <Button type="button" variant="secondary" onClick={onDone} disabled={returnMutation.isPending}>Cancel</Button>
    </div>
  );
}

function ScrapFromIssuedInlinePanel({ farmId, row, onDone }: { farmId: string; row: OutstandingIssuedMaterialRowRead; onDone: () => void }) {
  const [quantity, setQuantity] = useState("");
  const [reason, setReason] = useState("");
  const [error, setError] = useState<AppError | null>(null);
  const scrapMutation = useRecordInventoryScrap();
  const { uomsById } = useItemOptions();
  const uomCode = uomsById.get(row.base_uom_id);

  return (
    <div className="flex flex-wrap items-end gap-2 rounded-lg border border-wl-border bg-wl-surface-raised p-2">
      <label className="flex flex-col gap-1">
        <span className={labelClass}>Qty {uomCode ? `(${uomCode})` : ""}</span>
        <input
          className={inputClass} type="number" min="0" step="any" value={quantity}
          onChange={(e) => setQuantity(e.target.value)}
        />
      </label>
      <label className="flex flex-col gap-1">
        <span className={labelClass}>Reason</span>
        <input className={inputClass} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. spill" />
      </label>
      {error && <p className="text-[11px] text-danger-700">{error.message}</p>}
      <Button
        type="button" variant="primary"
        disabled={!quantity || Number(quantity) <= 0 || !reason.trim() || scrapMutation.isPending}
        onClick={() => {
          setError(null);
          scrapMutation.mutate(
            {
              farmId,
              payload: {
                client_command_id: crypto.randomUUID(), source_kind: "issued", issue_line_id: row.issue_line_id,
                quantity, reason: reason.trim(), effective_time: nowIso(),
              },
            },
            { onSuccess: onDone, onError: (err) => setError(asAppError(err)) },
          );
        }}
      >
        {scrapMutation.isPending ? "Recording…" : "Record scrap"}
      </Button>
      <Button type="button" variant="secondary" onClick={onDone} disabled={scrapMutation.isPending}>Cancel</Button>
    </div>
  );
}

function IssuedMaterialRow({ farmId, row, activeBins }: { farmId: string; row: OutstandingIssuedMaterialRowRead; activeBins: { id: string; label: string }[] }) {
  const [action, setAction] = useState<IssuedMaterialAction>(null);
  const { uomsById } = useItemOptions();
  const uomCode = uomsById.get(row.base_uom_id);

  return (
    <li className="rounded-xl border border-wl-border bg-wl-surface-raised">
      <div className="flex flex-wrap items-center justify-between gap-2 p-3 text-xs">
        <div className="flex flex-col gap-0.5">
          <span className="font-medium text-wl-text">{row.issue_code} · {row.purpose}</span>
          <span className="text-[11px] text-wl-text-tertiary">
            {row.item_name}{row.manufacturer_lot_reference ? ` — Lot ${row.manufacturer_lot_reference}` : ""}
          </span>
        </div>
        <div className="flex items-center gap-3 text-[11px] text-wl-text-secondary">
          <span>Issued: {formatQty(row.issued_quantity, uomCode)}</span>
          <span className="font-medium text-wl-text">Outstanding: {formatQty(row.outstanding_quantity, uomCode)}</span>
          <div className="flex gap-1">
            <button type="button" className="font-medium text-wl-brand hover:underline" onClick={() => setAction(action === "consume" ? null : "consume")}>Consume</button>
            <button type="button" className="font-medium text-wl-brand hover:underline" onClick={() => setAction(action === "return" ? null : "return")}>Return</button>
            <button type="button" className="font-medium text-wl-brand hover:underline" onClick={() => setAction(action === "scrap" ? null : "scrap")}>Scrap</button>
          </div>
        </div>
      </div>
      {action === "consume" && (
        <div className="border-t border-wl-border/60 p-2">
          <ConsumeInlinePanel farmId={farmId} row={row} onDone={() => setAction(null)} />
        </div>
      )}
      {action === "return" && (
        <div className="border-t border-wl-border/60 p-2">
          <ReturnInlinePanel farmId={farmId} row={row} activeBins={activeBins} onDone={() => setAction(null)} />
        </div>
      )}
      {action === "scrap" && (
        <div className="border-t border-wl-border/60 p-2">
          <ScrapFromIssuedInlinePanel farmId={farmId} row={row} onDone={() => setAction(null)} />
        </div>
      )}
    </li>
  );
}

function IssuedMaterialPanel({ farmId }: { farmId: string }) {
  const rowsQuery = useOutstandingIssuedMaterial(farmId);
  const treeQuery = useLocationsTree(farmId);
  const activeBins = activeBinsWithPaths(treeQuery.data ?? []);
  const rows = rowsQuery.data ?? [];

  if (rowsQuery.isLoading) return <p className="text-sm text-wl-text-secondary">Loading…</p>;
  if (rows.length === 0) return <p className="text-sm text-wl-text">No outstanding issued material.</p>;

  return (
    <ul className="flex flex-col gap-2">
      {rows.map((row) => (
        <IssuedMaterialRow key={row.issue_line_id} farmId={farmId} row={row} activeBins={activeBins} />
      ))}
    </ul>
  );
}

// --- PAGE ----------------------------------------------------------------------

/** STORE-INV-003: Issue -- one compact two-mode page, never separate
 * top-level Reservation/Issue modules. "Issue now" is Direct Issue; the
 * "Reservations" tab creates Reservations and issues/releases against
 * them via a compact per-line drawer. */
export default function StoreInventoryIssuePage() {
  const { farmId } = useParams<{ farmId: string }>();
  const [mode, setMode] = useState<"issue-now" | "reservations" | "issued-material">("issue-now");

  return (
    <div>
      <PageHeader
        title="Issue"
        description="Move material from Store Bin custody to farm-operational custody, and settle it once it's been consumed, returned, or scrapped."
        breadcrumbs={
          <Breadcrumbs
            items={[
              { label: "Home", href: `/farms/${farmId}` },
              { label: "Store & Inventory", href: `/farms/${farmId}/store-inventory` },
              { label: "Issue" },
            ]}
          />
        }
      />
      <div className="mb-4">
        <Tabs
          tabs={[
            { id: "issue-now", label: "Issue now" }, { id: "reservations", label: "Reservations" },
            { id: "issued-material", label: "Issued material" },
          ]}
          activeId={mode}
          onChange={(id) => setMode(id as "issue-now" | "reservations" | "issued-material")}
          aria-label="Issue mode"
        />
      </div>
      {mode === "issue-now" && <IssueNowPanel farmId={farmId} />}
      {mode === "reservations" && <ReservationsPanel farmId={farmId} />}
      {mode === "issued-material" && <IssuedMaterialPanel farmId={farmId} />}
    </div>
  );
}
