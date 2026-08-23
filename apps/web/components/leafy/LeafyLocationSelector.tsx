"use client";

import { FilterableSelect, type FilterableSelectOption } from "@/components/FilterableSelect";
import type { GreenhouseOverviewItem } from "@/lib/api/client";
import { useGreenhouseStructure } from "@/lib/query/hooks";

const labelClass = "block text-sm font-medium text-ink";
const errorClass = "text-xs text-red-700";
const inputClassBase =
  "min-h-11 rounded-md border border-border-subtle bg-surface px-3 text-sm text-ink focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-600";
const inputClass = `${inputClassBase} w-full`;

function Field({ label, error, children }: { label: string; error?: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1">
      <span className={labelClass}>{label}</span>
      {children}
      {error && <span className={errorClass}>{error}</span>}
    </label>
  );
}

export type LeafyLocationValue = {
  leafy_greenhouse_id: string;
  zone_id: string;
  span_id: string;
  destination_location_id: string;
  table_label: string;
  /** The selected Table's raw configured capacity (repository domain
   * convention: NULL means "not configured", effective capacity 1 -- see
   * `schema.gen.ts`'s own comment on this field). Derived from the
   * selection, not a separately editable value; always reset alongside
   * `destination_location_id`. */
  table_capacity: number | null;
};

/** NURSERY-OPS-005B section 21/24/47: a small, self-contained cascading
 * Greenhouse -> Zone -> Span -> Table picker -- no cascading-selection
 * pattern existed anywhere in this codebase before this ticket (confirmed
 * by discovery), so this is a genuinely new component rather than an
 * extraction of an existing one. Composed entirely from the existing,
 * already-proven `FilterableSelect` leaf control -- never a new selector
 * framework. Changing an ancestor resets every descendant (section 21,
 * frozen): Greenhouse change resets Zone/Span/Table; Zone change resets
 * Span/Table; Span change resets Table. One instance per destination card
 * (section 20, frozen: destinations may span different Leafy Greenhouses
 * in one atomic command), so this owns its own `useGreenhouseStructure`
 * call scoped to whichever Greenhouse THIS card currently has selected --
 * never a single structure query shared across every destination.
 * `table_label` carries the assembled ancestry string (`GH / Zone / Span /
 * Table`, section 22/25 -- Table codes may restart within a Span, so a
 * bare Table code is ambiguous without it) alongside the Table id, since
 * the Review/Success screens need it without a second lookup. */
export function LeafyLocationSelector({
  farmId,
  leafyGreenhouses,
  leafyGreenhousesLoading,
  value,
  onChange,
  errors,
}: {
  farmId: string;
  leafyGreenhouses: GreenhouseOverviewItem[];
  leafyGreenhousesLoading: boolean;
  value: LeafyLocationValue;
  onChange: (next: LeafyLocationValue) => void;
  errors?: {
    leafy_greenhouse_id?: { message?: string };
    zone_id?: { message?: string };
    span_id?: { message?: string };
    destination_location_id?: { message?: string };
  };
}) {
  const structureQuery = useGreenhouseStructure(farmId, value.leafy_greenhouse_id || "__none__");
  const zones = value.leafy_greenhouse_id ? (structureQuery.data?.leafy_zones ?? []) : [];
  const selectedZone = zones.find((z) => z.id === value.zone_id);
  const spans = selectedZone?.spans ?? [];
  const selectedSpan = spans.find((s) => s.id === value.span_id);
  const tables = selectedSpan?.tables ?? [];
  const selectedGreenhouse = leafyGreenhouses.find((g) => g.greenhouse_id === value.leafy_greenhouse_id);

  const zoneOptions: FilterableSelectOption[] = zones.map((z) => ({ value: z.id, label: z.code }));
  const spanOptions: FilterableSelectOption[] = spans.map((s) => ({ value: s.id, label: s.code }));
  const tableOptions: FilterableSelectOption[] = tables.map((t) => ({
    value: t.id,
    label: t.code,
    description: `capacity: ${t.capacity ?? "unlimited"}`,
  }));

  function ancestryLabel(tableCode: string): string {
    return [selectedGreenhouse?.code, selectedZone?.code, selectedSpan?.code, tableCode].filter(Boolean).join(" / ");
  }

  return (
    <div className="flex flex-col gap-3">
      {leafyGreenhouses.length > 1 && (
        <Field label="Leafy Greenhouse" error={errors?.leafy_greenhouse_id?.message}>
          <select
            value={value.leafy_greenhouse_id}
            onChange={(e) =>
              onChange({
                leafy_greenhouse_id: e.target.value, zone_id: "", span_id: "", destination_location_id: "",
                table_label: "", table_capacity: null,
              })
            }
            disabled={leafyGreenhousesLoading}
            className={inputClass}
          >
            <option value="">Select a Greenhouse…</option>
            {leafyGreenhouses.map((g) => (
              <option key={g.greenhouse_id} value={g.greenhouse_id}>
                {g.code}
              </option>
            ))}
          </select>
        </Field>
      )}

      <Field label="Zone" error={errors?.zone_id?.message}>
        <FilterableSelect
          aria-label="Zone"
          options={zoneOptions}
          value={value.zone_id}
          disabled={!value.leafy_greenhouse_id}
          loading={Boolean(value.leafy_greenhouse_id) && structureQuery.isLoading}
          placeholder="Search Zone by code…"
          emptyMessage="No Zones configured in this Greenhouse"
          onChange={(zoneId) =>
            onChange({
              ...value, zone_id: zoneId, span_id: "", destination_location_id: "",
              table_label: "", table_capacity: null,
            })
          }
        />
      </Field>

      <Field label="Span" error={errors?.span_id?.message}>
        <FilterableSelect
          aria-label="Span"
          options={spanOptions}
          value={value.span_id}
          disabled={!value.zone_id}
          placeholder="Search Span by code…"
          emptyMessage="No Spans configured in this Zone"
          onChange={(spanId) =>
            onChange({ ...value, span_id: spanId, destination_location_id: "", table_label: "", table_capacity: null })
          }
        />
      </Field>

      <Field label="Table" error={errors?.destination_location_id?.message}>
        <FilterableSelect
          aria-label="Table"
          options={tableOptions}
          value={value.destination_location_id}
          disabled={!value.span_id}
          placeholder="Search Table by code…"
          emptyMessage="No Tables configured in this Span"
          onChange={(tableId) => {
            const table = tables.find((t) => t.id === tableId);
            onChange({
              ...value, destination_location_id: tableId,
              table_label: table ? ancestryLabel(table.code) : "",
              table_capacity: table ? table.capacity ?? null : null,
            });
          }}
        />
      </Field>

      {value.table_label && <p className="text-xs text-ink-muted">{value.table_label}</p>}
    </div>
  );
}
