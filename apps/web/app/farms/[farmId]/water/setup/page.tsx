"use client";

import { useParams } from "next/navigation";
import { useMemo, useState } from "react";

import { ErrorState } from "@/components/ErrorState";
import { LoadingSkeleton } from "@/components/LoadingSkeleton";
import { PageHeader } from "@/components/PageHeader";
import { Breadcrumbs } from "@/components/Breadcrumbs";
import { StatusBadge } from "@/components/StatusBadge";
import { Button } from "@/components/ui/Button";
import { tableBodyDividerClass, tableHeadRowClass, tableRowHoverClass, tableTdClass, tableThClass, tableWrapperClass } from "@/components/ui/table";
import { WaterSubNav } from "@/components/water/WaterSubNav";
import type {
  CircuitDeliveryPointLinkOpen,
  IrrigationCircuitCreate,
  ReservoirCircuitLinkOpen,
  ReservoirCreate,
  ReturnPointReservoirLinkOpen,
  SamplingPointCreate,
  WaterDeliveryPointCreate,
  WaterReturnPointCreate,
  WaterSourceCreate,
  WaterSourceReservoirLinkOpen,
} from "@/lib/api/client";
import { AppError } from "@/lib/errors/adapter";
import { formatDateTimeWithZoneLabel } from "@/lib/format/datetime";
import { humanizeEnumCode } from "@/lib/format/humanize";
import { flattenLocationTree } from "@/lib/format/locationTree";
import {
  useCircuitDeliveryPointLinks,
  useCloseCircuitDeliveryPointLink,
  useCloseReservoirCircuitLink,
  useCloseReturnPointReservoirLink,
  useCloseWaterSourceReservoirLink,
  useCreateIrrigationCircuit,
  useCreateReservoir,
  useCreateSamplingPoint,
  useCreateWaterDeliveryPoint,
  useCreateWaterReturnPoint,
  useCreateWaterSource,
  useFarm,
  useIrrigationCircuits,
  useLocationsTree,
  useOpenCircuitDeliveryPointLink,
  useOpenReservoirCircuitLink,
  useOpenReturnPointReservoirLink,
  useOpenWaterSourceReservoirLink,
  useReservoirCircuitLinks,
  useReservoirs,
  useReturnPointReservoirLinks,
  useSamplingPoints,
  useUoms,
  useWaterDeliveryPoints,
  useWaterReturnPoints,
  useWaterSourceReservoirLinks,
  useWaterSources,
} from "@/lib/query/hooks";

function errorMessage(error: unknown): string {
  return error instanceof AppError ? error.message : "Something went wrong. Please try again.";
}

const inputClass =
  "min-h-10 w-full rounded-md border border-wl-border bg-wl-surface-raised px-3 text-sm text-wl-text focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-wl-focus";
const labelClass = "flex flex-col gap-1 text-sm";
const labelTextClass = "text-xs font-medium uppercase tracking-wide text-wl-text-secondary";
const errorTextClass = "text-xs text-wl-flag-fg";

const SECTIONS = [
  "sources", "reservoirs", "circuits", "delivery-points", "return-points", "sampling-points", "topology",
] as const;
type Section = (typeof SECTIONS)[number];
const SECTION_LABELS: Record<Section, string> = {
  sources: "Water Sources",
  reservoirs: "Reservoirs / Tanks",
  circuits: "Irrigation Circuits",
  "delivery-points": "Delivery Points",
  "return-points": "Return / Drain Points",
  "sampling-points": "Sampling Points",
  topology: "Topology Connections",
};

const SOURCE_TYPES = ["bore", "municipal", "ro_treated", "storage_tank_feed", "other"];
const RESERVOIR_TYPES = ["source_tank", "storage_tank", "mixing_tank", "nutrient_reservoir", "return_reservoir", "other"];

export default function WaterSetupPage() {
  const { farmId } = useParams<{ farmId: string }>();
  const [section, setSection] = useState<Section>("sources");

  return (
    <div>
      <PageHeader
        title="Water & Nutrients — System Setup"
        breadcrumbs={
          <Breadcrumbs items={[{ label: "Home", href: `/farms/${farmId}` }, { label: "Water & Nutrients", href: `/farms/${farmId}/water` }, { label: "System Setup" }]} />
        }
      />
      <WaterSubNav farmId={farmId} />

      <nav aria-label="Setup sections" className="mb-5 flex flex-wrap gap-1.5">
        {SECTIONS.map((s) => (
          <button
            key={s}
            type="button"
            onClick={() => setSection(s)}
            className={`min-h-9 rounded-lg px-3 text-sm font-medium ${
              section === s ? "bg-wl-brand-subtle text-wl-brand" : "bg-wl-surface-raised text-wl-text-secondary hover:bg-wl-surface-hover"
            }`}
          >
            {SECTION_LABELS[s]}
          </button>
        ))}
      </nav>

      {section === "sources" && <WaterSourcesSection farmId={farmId} />}
      {section === "reservoirs" && <ReservoirsSection farmId={farmId} />}
      {section === "circuits" && <CircuitsSection farmId={farmId} />}
      {section === "delivery-points" && <DeliveryPointsSection farmId={farmId} />}
      {section === "return-points" && <ReturnPointsSection farmId={farmId} />}
      {section === "sampling-points" && <SamplingPointsSection farmId={farmId} />}
      {section === "topology" && <TopologySection farmId={farmId} />}
    </div>
  );
}

function SectionShell({
  title, onNew, newing, children,
}: { title: string; onNew?: () => void; newing?: boolean; children: React.ReactNode }) {
  return (
    <section>
      <div className="mb-3 flex items-center justify-between">
        <h2 className="font-serif text-base font-semibold text-wl-text">{title}</h2>
        {onNew && !newing && (
          <Button variant="primary" onClick={onNew}>
            New
          </Button>
        )}
      </div>
      {children}
    </section>
  );
}

// --- Water Sources ---------------------------------------------------------------------

function WaterSourcesSection({ farmId }: { farmId: string }) {
  const query = useWaterSources(farmId);
  const createMutation = useCreateWaterSource(farmId);
  const [newing, setNewing] = useState(false);
  const [form, setForm] = useState({ code: "", name: "", source_type: "bore", notes: "" });
  const [error, setError] = useState<string | null>(null);

  function submit() {
    setError(null);
    const payload: WaterSourceCreate = {
      code: form.code, name: form.name, source_type: form.source_type, notes: form.notes || null,
    };
    createMutation.mutate(payload, {
      onSuccess: () => {
        setNewing(false);
        setForm({ code: "", name: "", source_type: "bore", notes: "" });
      },
      onError: (err) => setError(errorMessage(err)),
    });
  }

  return (
    <SectionShell title="Water Sources" onNew={() => setNewing(true)} newing={newing}>
      {newing && (
        <form
          onSubmit={(e) => { e.preventDefault(); submit(); }}
          className="mb-4 flex flex-col gap-3 rounded-xl border border-wl-border bg-wl-surface-raised p-4 sm:flex-row sm:flex-wrap sm:items-end"
        >
          <label className={labelClass}>
            <span className={labelTextClass}>Code</span>
            <input className={inputClass} value={form.code} onChange={(e) => setForm({ ...form, code: e.target.value })} required />
          </label>
          <label className={labelClass}>
            <span className={labelTextClass}>Name</span>
            <input className={inputClass} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required />
          </label>
          <label className={labelClass}>
            <span className={labelTextClass}>Source type</span>
            <select className={inputClass} value={form.source_type} onChange={(e) => setForm({ ...form, source_type: e.target.value })}>
              {SOURCE_TYPES.map((t) => <option key={t} value={t}>{humanizeEnumCode(t)}</option>)}
            </select>
          </label>
          <label className={`${labelClass} sm:min-w-48 sm:flex-1`}>
            <span className={labelTextClass}>Notes</span>
            <input className={inputClass} value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} />
          </label>
          {error && <p className={errorTextClass} role="alert">{error}</p>}
          <div className="flex gap-2">
            <Button type="button" variant="secondary" onClick={() => setNewing(false)}>Cancel</Button>
            <Button type="submit" variant="primary" disabled={createMutation.isPending}>
              {createMutation.isPending ? "Saving…" : "Save"}
            </Button>
          </div>
        </form>
      )}
      {query.isLoading && <LoadingSkeleton rows={3} label="Loading water sources" />}
      {query.error && <ErrorState error={query.error} onRetry={() => query.refetch()} />}
      {query.data && query.data.length === 0 && !newing && <p className="text-sm text-wl-text-secondary">No Water Sources configured yet.</p>}
      {query.data && query.data.length > 0 && (
        <div className={tableWrapperClass}>
          <table className="w-full text-sm">
            <thead><tr className={tableHeadRowClass}><th className={tableThClass}>Code</th><th className={tableThClass}>Name</th><th className={tableThClass}>Type</th><th className={tableThClass}>Status</th></tr></thead>
            <tbody className={tableBodyDividerClass}>
              {query.data.map((s) => (
                <tr key={s.id} className={tableRowHoverClass}>
                  <td className={`${tableTdClass} font-medium text-wl-text`}>{s.code}</td>
                  <td className={tableTdClass}>{s.name}</td>
                  <td className={tableTdClass}>{humanizeEnumCode(s.source_type)}</td>
                  <td className={tableTdClass}><StatusBadge label={humanizeEnumCode(s.status)} tone={s.status === "active" ? "active" : "neutral"} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </SectionShell>
  );
}

// --- Reservoirs / Tanks -----------------------------------------------------------------

function ReservoirsSection({ farmId }: { farmId: string }) {
  const query = useReservoirs(farmId);
  const uomsQuery = useUoms();
  const createMutation = useCreateReservoir(farmId);
  const [newing, setNewing] = useState(false);
  const [form, setForm] = useState({ code: "", name: "", reservoir_type: "nutrient_reservoir", nominal_capacity: "", nominal_capacity_uom_id: "", notes: "" });
  const [error, setError] = useState<string | null>(null);
  const volumeUoms = useMemo(() => (uomsQuery.data ?? []).filter((u) => u.quantity_kind === "volume"), [uomsQuery.data]);

  function submit() {
    setError(null);
    const payload: ReservoirCreate = {
      code: form.code, name: form.name, reservoir_type: form.reservoir_type,
      nominal_capacity: form.nominal_capacity ? Number(form.nominal_capacity) : null,
      nominal_capacity_uom_id: form.nominal_capacity ? form.nominal_capacity_uom_id || null : null,
      notes: form.notes || null,
    };
    createMutation.mutate(payload, {
      onSuccess: () => {
        setNewing(false);
        setForm({ code: "", name: "", reservoir_type: "nutrient_reservoir", nominal_capacity: "", nominal_capacity_uom_id: "", notes: "" });
      },
      onError: (err) => setError(errorMessage(err)),
    });
  }

  return (
    <SectionShell title="Reservoirs / Tanks" onNew={() => setNewing(true)} newing={newing}>
      {newing && (
        <form
          onSubmit={(e) => { e.preventDefault(); submit(); }}
          className="mb-4 flex flex-col gap-3 rounded-xl border border-wl-border bg-wl-surface-raised p-4 sm:flex-row sm:flex-wrap sm:items-end"
        >
          <label className={labelClass}>
            <span className={labelTextClass}>Code</span>
            <input className={inputClass} value={form.code} onChange={(e) => setForm({ ...form, code: e.target.value })} required />
          </label>
          <label className={labelClass}>
            <span className={labelTextClass}>Name</span>
            <input className={inputClass} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required />
          </label>
          <label className={labelClass}>
            <span className={labelTextClass}>Type</span>
            <select className={inputClass} value={form.reservoir_type} onChange={(e) => setForm({ ...form, reservoir_type: e.target.value })}>
              {RESERVOIR_TYPES.map((t) => <option key={t} value={t}>{humanizeEnumCode(t)}</option>)}
            </select>
          </label>
          <label className={labelClass}>
            <span className={labelTextClass}>Nominal capacity</span>
            <input type="number" min="0" step="any" className={inputClass} value={form.nominal_capacity} onChange={(e) => setForm({ ...form, nominal_capacity: e.target.value })} placeholder="Not recorded" />
          </label>
          <label className={labelClass}>
            <span className={labelTextClass}>Capacity unit</span>
            <select className={inputClass} value={form.nominal_capacity_uom_id} onChange={(e) => setForm({ ...form, nominal_capacity_uom_id: e.target.value })} disabled={!form.nominal_capacity}>
              <option value="">—</option>
              {volumeUoms.map((u) => <option key={u.id} value={u.id}>{u.code}</option>)}
            </select>
          </label>
          <label className={`${labelClass} sm:min-w-48 sm:flex-1`}>
            <span className={labelTextClass}>Notes</span>
            <input className={inputClass} value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} />
          </label>
          {error && <p className={errorTextClass} role="alert">{error}</p>}
          <div className="flex gap-2">
            <Button type="button" variant="secondary" onClick={() => setNewing(false)}>Cancel</Button>
            <Button type="submit" variant="primary" disabled={createMutation.isPending}>
              {createMutation.isPending ? "Saving…" : "Save"}
            </Button>
          </div>
        </form>
      )}
      {query.isLoading && <LoadingSkeleton rows={3} label="Loading reservoirs" />}
      {query.error && <ErrorState error={query.error} onRetry={() => query.refetch()} />}
      {query.data && query.data.length === 0 && !newing && <p className="text-sm text-wl-text-secondary">No Reservoirs/Tanks configured yet.</p>}
      {query.data && query.data.length > 0 && (
        <div className={tableWrapperClass}>
          <table className="w-full text-sm">
            <thead><tr className={tableHeadRowClass}><th className={tableThClass}>Code</th><th className={tableThClass}>Name</th><th className={tableThClass}>Type</th><th className={tableThClass}>Capacity</th><th className={tableThClass}>Status</th></tr></thead>
            <tbody className={tableBodyDividerClass}>
              {query.data.map((r) => (
                <tr key={r.id} className={tableRowHoverClass}>
                  <td className={`${tableTdClass} font-medium text-wl-text`}>{r.code}</td>
                  <td className={tableTdClass}>{r.name}</td>
                  <td className={tableTdClass}>{humanizeEnumCode(r.reservoir_type)}</td>
                  <td className={tableTdClass}>{r.nominal_capacity ?? "Not recorded"}</td>
                  <td className={tableTdClass}><StatusBadge label={humanizeEnumCode(r.status)} tone={r.status === "active" ? "active" : "neutral"} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </SectionShell>
  );
}

// --- Irrigation Circuits -----------------------------------------------------------------

function CircuitsSection({ farmId }: { farmId: string }) {
  const query = useIrrigationCircuits(farmId);
  const createMutation = useCreateIrrigationCircuit(farmId);
  const [newing, setNewing] = useState(false);
  const [form, setForm] = useState({ code: "", name: "", system_type: "", notes: "" });
  const [error, setError] = useState<string | null>(null);

  function submit() {
    setError(null);
    const payload: IrrigationCircuitCreate = { code: form.code, name: form.name, system_type: form.system_type || null, notes: form.notes || null };
    createMutation.mutate(payload, {
      onSuccess: () => { setNewing(false); setForm({ code: "", name: "", system_type: "", notes: "" }); },
      onError: (err) => setError(errorMessage(err)),
    });
  }

  return (
    <SectionShell title="Irrigation Circuits" onNew={() => setNewing(true)} newing={newing}>
      {newing && (
        <form onSubmit={(e) => { e.preventDefault(); submit(); }} className="mb-4 flex flex-col gap-3 rounded-xl border border-wl-border bg-wl-surface-raised p-4 sm:flex-row sm:flex-wrap sm:items-end">
          <label className={labelClass}>
            <span className={labelTextClass}>Code</span>
            <input className={inputClass} value={form.code} onChange={(e) => setForm({ ...form, code: e.target.value })} required />
          </label>
          <label className={labelClass}>
            <span className={labelTextClass}>Name</span>
            <input className={inputClass} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required />
          </label>
          <label className={labelClass}>
            <span className={labelTextClass}>System type</span>
            <input className={inputClass} placeholder="e.g. DWC, drip" value={form.system_type} onChange={(e) => setForm({ ...form, system_type: e.target.value })} />
          </label>
          <label className={`${labelClass} sm:min-w-48 sm:flex-1`}>
            <span className={labelTextClass}>Notes</span>
            <input className={inputClass} value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} />
          </label>
          {error && <p className={errorTextClass} role="alert">{error}</p>}
          <div className="flex gap-2">
            <Button type="button" variant="secondary" onClick={() => setNewing(false)}>Cancel</Button>
            <Button type="submit" variant="primary" disabled={createMutation.isPending}>{createMutation.isPending ? "Saving…" : "Save"}</Button>
          </div>
        </form>
      )}
      {query.isLoading && <LoadingSkeleton rows={3} label="Loading irrigation circuits" />}
      {query.error && <ErrorState error={query.error} onRetry={() => query.refetch()} />}
      {query.data && query.data.length === 0 && !newing && <p className="text-sm text-wl-text-secondary">No Irrigation Circuits configured yet.</p>}
      {query.data && query.data.length > 0 && (
        <div className={tableWrapperClass}>
          <table className="w-full text-sm">
            <thead><tr className={tableHeadRowClass}><th className={tableThClass}>Code</th><th className={tableThClass}>Name</th><th className={tableThClass}>System type</th><th className={tableThClass}>Status</th></tr></thead>
            <tbody className={tableBodyDividerClass}>
              {query.data.map((c) => (
                <tr key={c.id} className={tableRowHoverClass}>
                  <td className={`${tableTdClass} font-medium text-wl-text`}>{c.code}</td>
                  <td className={tableTdClass}>{c.name}</td>
                  <td className={tableTdClass}>{c.system_type ?? "—"}</td>
                  <td className={tableTdClass}><StatusBadge label={humanizeEnumCode(c.status)} tone={c.status === "active" ? "active" : "neutral"} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </SectionShell>
  );
}

// --- Delivery Points ---------------------------------------------------------------------

function DeliveryPointsSection({ farmId }: { farmId: string }) {
  const query = useWaterDeliveryPoints(farmId);
  const locationsQuery = useLocationsTree(farmId);
  const createMutation = useCreateWaterDeliveryPoint(farmId);
  const [newing, setNewing] = useState(false);
  const [form, setForm] = useState({ code: "", name: "", location_id: "", notes: "" });
  const [error, setError] = useState<string | null>(null);
  const locationOptions = useMemo(() => flattenLocationTree(locationsQuery.data ?? []), [locationsQuery.data]);

  function submit() {
    setError(null);
    if (!form.location_id) { setError("A Location is required."); return; }
    const payload: WaterDeliveryPointCreate = { code: form.code, name: form.name, location_id: form.location_id, notes: form.notes || null };
    createMutation.mutate(payload, {
      onSuccess: () => { setNewing(false); setForm({ code: "", name: "", location_id: "", notes: "" }); },
      onError: (err) => setError(errorMessage(err)),
    });
  }

  return (
    <SectionShell title="Delivery Points" onNew={() => setNewing(true)} newing={newing}>
      <p className="mb-3 text-sm text-wl-text-secondary">
        A Delivery Point links an Irrigation Circuit to a real crop Location — a Table/Gutter leaf, or a larger
        ancestor (e.g. a whole Zone) when that is how the physical plumbing actually serves it.
      </p>
      {newing && (
        <form onSubmit={(e) => { e.preventDefault(); submit(); }} className="mb-4 flex flex-col gap-3 rounded-xl border border-wl-border bg-wl-surface-raised p-4 sm:flex-row sm:flex-wrap sm:items-end">
          <label className={labelClass}>
            <span className={labelTextClass}>Code</span>
            <input className={inputClass} value={form.code} onChange={(e) => setForm({ ...form, code: e.target.value })} required />
          </label>
          <label className={labelClass}>
            <span className={labelTextClass}>Name</span>
            <input className={inputClass} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required />
          </label>
          <label className={labelClass}>
            <span className={labelTextClass}>Location</span>
            <select className={inputClass} value={form.location_id} onChange={(e) => setForm({ ...form, location_id: e.target.value })} required>
              <option value="">Select a Location…</option>
              {locationOptions.map((l) => <option key={l.id} value={l.id}>{l.label}</option>)}
            </select>
          </label>
          <label className={`${labelClass} sm:min-w-48 sm:flex-1`}>
            <span className={labelTextClass}>Notes</span>
            <input className={inputClass} value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} />
          </label>
          {error && <p className={errorTextClass} role="alert">{error}</p>}
          <div className="flex gap-2">
            <Button type="button" variant="secondary" onClick={() => setNewing(false)}>Cancel</Button>
            <Button type="submit" variant="primary" disabled={createMutation.isPending}>{createMutation.isPending ? "Saving…" : "Save"}</Button>
          </div>
        </form>
      )}
      {query.isLoading && <LoadingSkeleton rows={3} label="Loading delivery points" />}
      {query.error && <ErrorState error={query.error} onRetry={() => query.refetch()} />}
      {query.data && query.data.length === 0 && !newing && <p className="text-sm text-wl-text-secondary">No Delivery Points configured yet.</p>}
      {query.data && query.data.length > 0 && (
        <div className={tableWrapperClass}>
          <table className="w-full text-sm">
            <thead><tr className={tableHeadRowClass}><th className={tableThClass}>Code</th><th className={tableThClass}>Name</th><th className={tableThClass}>Status</th></tr></thead>
            <tbody className={tableBodyDividerClass}>
              {query.data.map((d) => (
                <tr key={d.id} className={tableRowHoverClass}>
                  <td className={`${tableTdClass} font-medium text-wl-text`}>{d.code}</td>
                  <td className={tableTdClass}>{d.name}</td>
                  <td className={tableTdClass}><StatusBadge label={humanizeEnumCode(d.status)} tone={d.status === "active" ? "active" : "neutral"} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </SectionShell>
  );
}

// --- Return / Drain Points ----------------------------------------------------------------

function ReturnPointsSection({ farmId }: { farmId: string }) {
  const query = useWaterReturnPoints(farmId);
  const locationsQuery = useLocationsTree(farmId);
  const createMutation = useCreateWaterReturnPoint(farmId);
  const [newing, setNewing] = useState(false);
  const [form, setForm] = useState({ code: "", name: "", location_id: "", notes: "" });
  const [error, setError] = useState<string | null>(null);
  const locationOptions = useMemo(() => flattenLocationTree(locationsQuery.data ?? []), [locationsQuery.data]);

  function submit() {
    setError(null);
    const payload: WaterReturnPointCreate = { code: form.code, name: form.name, location_id: form.location_id || null, notes: form.notes || null };
    createMutation.mutate(payload, {
      onSuccess: () => { setNewing(false); setForm({ code: "", name: "", location_id: "", notes: "" }); },
      onError: (err) => setError(errorMessage(err)),
    });
  }

  return (
    <SectionShell title="Return / Drain Points" onNew={() => setNewing(true)} newing={newing}>
      <p className="mb-3 text-sm text-wl-text-secondary">
        Location is optional here — a drain-to-waste point may exist with no Location at all. Whether it recirculates
        is a fact of its own Topology Connection (a linked Return Reservoir), not a flag on this row.
      </p>
      {newing && (
        <form onSubmit={(e) => { e.preventDefault(); submit(); }} className="mb-4 flex flex-col gap-3 rounded-xl border border-wl-border bg-wl-surface-raised p-4 sm:flex-row sm:flex-wrap sm:items-end">
          <label className={labelClass}>
            <span className={labelTextClass}>Code</span>
            <input className={inputClass} value={form.code} onChange={(e) => setForm({ ...form, code: e.target.value })} required />
          </label>
          <label className={labelClass}>
            <span className={labelTextClass}>Name</span>
            <input className={inputClass} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required />
          </label>
          <label className={labelClass}>
            <span className={labelTextClass}>Location (optional)</span>
            <select className={inputClass} value={form.location_id} onChange={(e) => setForm({ ...form, location_id: e.target.value })}>
              <option value="">—</option>
              {locationOptions.map((l) => <option key={l.id} value={l.id}>{l.label}</option>)}
            </select>
          </label>
          <label className={`${labelClass} sm:min-w-48 sm:flex-1`}>
            <span className={labelTextClass}>Notes</span>
            <input className={inputClass} value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} />
          </label>
          {error && <p className={errorTextClass} role="alert">{error}</p>}
          <div className="flex gap-2">
            <Button type="button" variant="secondary" onClick={() => setNewing(false)}>Cancel</Button>
            <Button type="submit" variant="primary" disabled={createMutation.isPending}>{createMutation.isPending ? "Saving…" : "Save"}</Button>
          </div>
        </form>
      )}
      {query.isLoading && <LoadingSkeleton rows={3} label="Loading return points" />}
      {query.error && <ErrorState error={query.error} onRetry={() => query.refetch()} />}
      {query.data && query.data.length === 0 && !newing && <p className="text-sm text-wl-text-secondary">No Return/Drain Points configured yet.</p>}
      {query.data && query.data.length > 0 && (
        <div className={tableWrapperClass}>
          <table className="w-full text-sm">
            <thead><tr className={tableHeadRowClass}><th className={tableThClass}>Code</th><th className={tableThClass}>Name</th><th className={tableThClass}>Status</th></tr></thead>
            <tbody className={tableBodyDividerClass}>
              {query.data.map((d) => (
                <tr key={d.id} className={tableRowHoverClass}>
                  <td className={`${tableTdClass} font-medium text-wl-text`}>{d.code}</td>
                  <td className={tableTdClass}>{d.name}</td>
                  <td className={tableTdClass}><StatusBadge label={humanizeEnumCode(d.status)} tone={d.status === "active" ? "active" : "neutral"} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </SectionShell>
  );
}

// --- Sampling Points -----------------------------------------------------------------------

const POINT_TYPES = ["source", "reservoir", "circuit_supply", "delivery", "drain_return", "other"] as const;

function SamplingPointsSection({ farmId }: { farmId: string }) {
  const query = useSamplingPoints(farmId);
  const sourcesQuery = useWaterSources(farmId);
  const reservoirsQuery = useReservoirs(farmId);
  const circuitsQuery = useIrrigationCircuits(farmId);
  const deliveryPointsQuery = useWaterDeliveryPoints(farmId);
  const returnPointsQuery = useWaterReturnPoints(farmId);
  const createMutation = useCreateSamplingPoint(farmId);
  const [newing, setNewing] = useState(false);
  const [form, setForm] = useState({ code: "", name: "", point_type: "reservoir" as string, anchor_id: "", notes: "" });
  const [error, setError] = useState<string | null>(null);

  const anchorOptions = useMemo(() => {
    switch (form.point_type) {
      case "source": return (sourcesQuery.data ?? []).map((s) => ({ id: s.id, label: `${s.code} — ${s.name}` }));
      case "reservoir": return (reservoirsQuery.data ?? []).map((r) => ({ id: r.id, label: `${r.code} — ${r.name}` }));
      case "circuit_supply": return (circuitsQuery.data ?? []).map((c) => ({ id: c.id, label: `${c.code} — ${c.name}` }));
      case "delivery": return (deliveryPointsQuery.data ?? []).map((d) => ({ id: d.id, label: `${d.code} — ${d.name}` }));
      case "drain_return": return (returnPointsQuery.data ?? []).map((r) => ({ id: r.id, label: `${r.code} — ${r.name}` }));
      default: return [];
    }
  }, [form.point_type, sourcesQuery.data, reservoirsQuery.data, circuitsQuery.data, deliveryPointsQuery.data, returnPointsQuery.data]);

  function submit() {
    setError(null);
    if (form.point_type !== "other" && !form.anchor_id) { setError("An anchor is required for this point type."); return; }
    const payload: SamplingPointCreate = {
      code: form.code, name: form.name, point_type: form.point_type,
      anchor_id: form.point_type === "other" ? null : form.anchor_id, notes: form.notes || null,
    };
    createMutation.mutate(payload, {
      onSuccess: () => { setNewing(false); setForm({ code: "", name: "", point_type: "reservoir", anchor_id: "", notes: "" }); },
      onError: (err) => setError(errorMessage(err)),
    });
  }

  return (
    <SectionShell title="Sampling Points" onNew={() => setNewing(true)} newing={newing}>
      <p className="mb-3 text-sm text-wl-text-secondary">
        A Sampling Point always anchors to a real Reservoir/Circuit/Delivery/Return/Source — never a floating point.
      </p>
      {newing && (
        <form onSubmit={(e) => { e.preventDefault(); submit(); }} className="mb-4 flex flex-col gap-3 rounded-xl border border-wl-border bg-wl-surface-raised p-4 sm:flex-row sm:flex-wrap sm:items-end">
          <label className={labelClass}>
            <span className={labelTextClass}>Code</span>
            <input className={inputClass} value={form.code} onChange={(e) => setForm({ ...form, code: e.target.value })} required />
          </label>
          <label className={labelClass}>
            <span className={labelTextClass}>Name</span>
            <input className={inputClass} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required />
          </label>
          <label className={labelClass}>
            <span className={labelTextClass}>Point type</span>
            <select className={inputClass} value={form.point_type} onChange={(e) => setForm({ ...form, point_type: e.target.value, anchor_id: "" })}>
              {POINT_TYPES.map((t) => <option key={t} value={t}>{humanizeEnumCode(t)}</option>)}
            </select>
          </label>
          {form.point_type !== "other" && (
            <label className={labelClass}>
              <span className={labelTextClass}>Anchor</span>
              <select className={inputClass} value={form.anchor_id} onChange={(e) => setForm({ ...form, anchor_id: e.target.value })} required>
                <option value="">Select…</option>
                {anchorOptions.map((o) => <option key={o.id} value={o.id}>{o.label}</option>)}
              </select>
            </label>
          )}
          <label className={`${labelClass} sm:min-w-48 sm:flex-1`}>
            <span className={labelTextClass}>Notes</span>
            <input className={inputClass} value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} />
          </label>
          {error && <p className={errorTextClass} role="alert">{error}</p>}
          <div className="flex gap-2">
            <Button type="button" variant="secondary" onClick={() => setNewing(false)}>Cancel</Button>
            <Button type="submit" variant="primary" disabled={createMutation.isPending}>{createMutation.isPending ? "Saving…" : "Save"}</Button>
          </div>
        </form>
      )}
      {query.isLoading && <LoadingSkeleton rows={3} label="Loading sampling points" />}
      {query.error && <ErrorState error={query.error} onRetry={() => query.refetch()} />}
      {query.data && query.data.length === 0 && !newing && <p className="text-sm text-wl-text-secondary">No Sampling Points configured yet.</p>}
      {query.data && query.data.length > 0 && (
        <div className={tableWrapperClass}>
          <table className="w-full text-sm">
            <thead><tr className={tableHeadRowClass}><th className={tableThClass}>Code</th><th className={tableThClass}>Name</th><th className={tableThClass}>Type</th><th className={tableThClass}>Status</th></tr></thead>
            <tbody className={tableBodyDividerClass}>
              {query.data.map((p) => (
                <tr key={p.id} className={tableRowHoverClass}>
                  <td className={`${tableTdClass} font-medium text-wl-text`}>{p.code}</td>
                  <td className={tableTdClass}>{p.name}</td>
                  <td className={tableTdClass}>{humanizeEnumCode(p.point_type)}</td>
                  <td className={tableTdClass}><StatusBadge label={humanizeEnumCode(p.status)} tone={p.status === "active" ? "active" : "neutral"} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </SectionShell>
  );
}

// --- Topology Connections ------------------------------------------------------------------

function LinkTable({
  title, rows, timezone, endpointLabel, onClose, closing,
}: {
  title: string;
  rows: { id: string; effective_from: string; effective_to: string | null; reason: string | null; endpoint: string }[];
  timezone?: string;
  endpointLabel: string;
  onClose: (linkId: string) => void;
  closing: string | null;
}) {
  return (
    <div>
      <h3 className="mb-2 text-sm font-semibold text-wl-text">{title}</h3>
      {rows.length === 0 && <p className="mb-4 text-sm text-wl-text-secondary">No connections recorded yet.</p>}
      {rows.length > 0 && (
        <div className={`${tableWrapperClass} mb-4`}>
          <table className="w-full text-sm">
            <thead>
              <tr className={tableHeadRowClass}>
                <th className={tableThClass}>{endpointLabel}</th>
                <th className={tableThClass}>Effective from</th>
                <th className={tableThClass}>Effective to</th>
                <th className={tableThClass}>Reason</th>
                <th className={tableThClass} />
              </tr>
            </thead>
            <tbody className={tableBodyDividerClass}>
              {rows.map((row) => (
                <tr key={row.id} className={tableRowHoverClass}>
                  <td className={`${tableTdClass} font-medium text-wl-text`}>{row.endpoint}</td>
                  <td className={tableTdClass}>{formatDateTimeWithZoneLabel(row.effective_from, timezone)}</td>
                  <td className={tableTdClass}>
                    {row.effective_to ? (
                      formatDateTimeWithZoneLabel(row.effective_to, timezone)
                    ) : (
                      <StatusBadge label="Current" tone="active" />
                    )}
                  </td>
                  <td className={tableTdClass}>{row.reason ?? "—"}</td>
                  <td className={tableTdClass}>
                    {!row.effective_to && (
                      <button
                        type="button"
                        className="text-sm font-medium text-wl-brand hover:underline disabled:text-wl-text-tertiary"
                        disabled={closing === row.id}
                        onClick={() => onClose(row.id)}
                      >
                        {closing === row.id ? "Closing…" : "Close"}
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function TopologySection({ farmId }: { farmId: string }) {
  const { data: farm } = useFarm(farmId);
  const sourcesQuery = useWaterSources(farmId);
  const reservoirsQuery = useReservoirs(farmId);
  const circuitsQuery = useIrrigationCircuits(farmId);
  const deliveryPointsQuery = useWaterDeliveryPoints(farmId);
  const returnPointsQuery = useWaterReturnPoints(farmId);

  const sourceLinks = useWaterSourceReservoirLinks(farmId);
  const circuitLinks = useReservoirCircuitLinks(farmId);
  const deliveryLinks = useCircuitDeliveryPointLinks(farmId);
  const returnLinks = useReturnPointReservoirLinks(farmId);

  const openSourceLink = useOpenWaterSourceReservoirLink(farmId);
  const closeSourceLink = useCloseWaterSourceReservoirLink(farmId);
  const openCircuitLink = useOpenReservoirCircuitLink(farmId);
  const closeCircuitLink = useCloseReservoirCircuitLink(farmId);
  const openDeliveryLink = useOpenCircuitDeliveryPointLink(farmId);
  const closeDeliveryLink = useCloseCircuitDeliveryPointLink(farmId);
  const openReturnLink = useOpenReturnPointReservoirLink(farmId);
  const closeReturnLink = useCloseReturnPointReservoirLink(farmId);

  const [closingId, setClosingId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const sourceById = useMemo(() => new Map((sourcesQuery.data ?? []).map((s) => [s.id, s])), [sourcesQuery.data]);
  const reservoirById = useMemo(() => new Map((reservoirsQuery.data ?? []).map((r) => [r.id, r])), [reservoirsQuery.data]);
  const circuitById = useMemo(() => new Map((circuitsQuery.data ?? []).map((c) => [c.id, c])), [circuitsQuery.data]);
  const deliveryPointById = useMemo(() => new Map((deliveryPointsQuery.data ?? []).map((d) => [d.id, d])), [deliveryPointsQuery.data]);
  const returnPointById = useMemo(() => new Map((returnPointsQuery.data ?? []).map((r) => [r.id, r])), [returnPointsQuery.data]);

  function close(kind: "source" | "circuit" | "delivery" | "return", linkId: string) {
    setError(null);
    setClosingId(linkId);
    const nowIso = new Date().toISOString();
    const mutation = { source: closeSourceLink, circuit: closeCircuitLink, delivery: closeDeliveryLink, return: closeReturnLink }[kind];
    mutation.mutate(
      { linkId, payload: { effective_to: nowIso } },
      { onSettled: () => setClosingId(null), onError: (err) => setError(errorMessage(err)) },
    );
  }

  const [openForm, setOpenForm] = useState<null | "source" | "circuit" | "delivery" | "return">(null);
  const [selection, setSelection] = useState({ from: "", to: "", reason: "" });

  function submitOpen() {
    setError(null);
    if (!selection.from || !selection.to) { setError("Both endpoints are required."); return; }
    const nowIso = new Date().toISOString();
    if (openForm === "source") {
      openSourceLink.mutate(
        { water_source_id: selection.from, reservoir_id: selection.to, effective_from: nowIso, reason: selection.reason || null } satisfies WaterSourceReservoirLinkOpen,
        { onSuccess: () => { setOpenForm(null); setSelection({ from: "", to: "", reason: "" }); }, onError: (err) => setError(errorMessage(err)) },
      );
    } else if (openForm === "circuit") {
      openCircuitLink.mutate(
        { reservoir_id: selection.from, irrigation_circuit_id: selection.to, effective_from: nowIso, reason: selection.reason || null } satisfies ReservoirCircuitLinkOpen,
        { onSuccess: () => { setOpenForm(null); setSelection({ from: "", to: "", reason: "" }); }, onError: (err) => setError(errorMessage(err)) },
      );
    } else if (openForm === "delivery") {
      openDeliveryLink.mutate(
        { irrigation_circuit_id: selection.from, water_delivery_point_id: selection.to, effective_from: nowIso, reason: selection.reason || null } satisfies CircuitDeliveryPointLinkOpen,
        { onSuccess: () => { setOpenForm(null); setSelection({ from: "", to: "", reason: "" }); }, onError: (err) => setError(errorMessage(err)) },
      );
    } else if (openForm === "return") {
      openReturnLink.mutate(
        { water_return_point_id: selection.from, return_reservoir_id: selection.to, effective_from: nowIso, reason: selection.reason || null } satisfies ReturnPointReservoirLinkOpen,
        { onSuccess: () => { setOpenForm(null); setSelection({ from: "", to: "", reason: "" }); }, onError: (err) => setError(errorMessage(err)) },
      );
    }
  }

  const fromOptions: Record<string, { id: string; label: string }[]> = {
    source: (sourcesQuery.data ?? []).map((s) => ({ id: s.id, label: `${s.code} — ${s.name}` })),
    circuit: (reservoirsQuery.data ?? []).map((r) => ({ id: r.id, label: `${r.code} — ${r.name}` })),
    delivery: (circuitsQuery.data ?? []).map((c) => ({ id: c.id, label: `${c.code} — ${c.name}` })),
    return: (returnPointsQuery.data ?? []).map((r) => ({ id: r.id, label: `${r.code} — ${r.name}` })),
  };
  const toOptions: Record<string, { id: string; label: string }[]> = {
    source: (reservoirsQuery.data ?? []).map((r) => ({ id: r.id, label: `${r.code} — ${r.name}` })),
    circuit: (circuitsQuery.data ?? []).map((c) => ({ id: c.id, label: `${c.code} — ${c.name}` })),
    delivery: (deliveryPointsQuery.data ?? []).map((d) => ({ id: d.id, label: `${d.code} — ${d.name}` })),
    return: (reservoirsQuery.data ?? []).map((r) => ({ id: r.id, label: `${r.code} — ${r.name}` })),
  };
  const formLabels: Record<string, [string, string]> = {
    source: ["Water Source", "Reservoir"],
    circuit: ["Reservoir", "Irrigation Circuit"],
    delivery: ["Irrigation Circuit", "Delivery Point"],
    return: ["Return Point", "Return Reservoir"],
  };

  const anyLoading = sourceLinks.isLoading || circuitLinks.isLoading || deliveryLinks.isLoading || returnLinks.isLoading;
  const anyError = sourceLinks.error || circuitLinks.error || deliveryLinks.error || returnLinks.error;

  return (
    <section>
      <p className="mb-4 text-sm text-wl-text-secondary">
        Effective-dated connections — closing one never rewrites it; a new connection is always a new row. Current
        (open-ended) connections show as <StatusBadge label="Current" tone="active" />; closed ones keep their own
        effective_to permanently.
      </p>

      {openForm && (
        <form
          onSubmit={(e) => { e.preventDefault(); submitOpen(); }}
          className="mb-5 flex flex-col gap-3 rounded-xl border border-wl-border bg-wl-surface-raised p-4 sm:flex-row sm:flex-wrap sm:items-end"
        >
          <label className={labelClass}>
            <span className={labelTextClass}>{formLabels[openForm][0]}</span>
            <select className={inputClass} value={selection.from} onChange={(e) => setSelection({ ...selection, from: e.target.value })} required>
              <option value="">Select…</option>
              {fromOptions[openForm].map((o) => <option key={o.id} value={o.id}>{o.label}</option>)}
            </select>
          </label>
          <label className={labelClass}>
            <span className={labelTextClass}>{formLabels[openForm][1]}</span>
            <select className={inputClass} value={selection.to} onChange={(e) => setSelection({ ...selection, to: e.target.value })} required>
              <option value="">Select…</option>
              {toOptions[openForm].map((o) => <option key={o.id} value={o.id}>{o.label}</option>)}
            </select>
          </label>
          <label className={`${labelClass} sm:min-w-48 sm:flex-1`}>
            <span className={labelTextClass}>Reason (optional)</span>
            <input className={inputClass} value={selection.reason} onChange={(e) => setSelection({ ...selection, reason: e.target.value })} />
          </label>
          <p className="w-full text-xs text-wl-text-secondary">Effective from now. To backdate this connection, use the read model&apos;s own history once recorded.</p>
          {error && <p className={errorTextClass} role="alert">{error}</p>}
          <div className="flex gap-2">
            <Button type="button" variant="secondary" onClick={() => { setOpenForm(null); setSelection({ from: "", to: "", reason: "" }); }}>Cancel</Button>
            <Button type="submit" variant="primary">Connect</Button>
          </div>
        </form>
      )}

      {anyLoading && <LoadingSkeleton rows={4} label="Loading topology" />}
      {anyError && <ErrorState error={anyError} onRetry={() => { sourceLinks.refetch(); circuitLinks.refetch(); deliveryLinks.refetch(); returnLinks.refetch(); }} />}

      {!anyLoading && !anyError && (
        <div className="flex flex-col gap-6">
          <div>
            <div className="mb-2 flex items-center justify-between">
              <span className="text-xs font-semibold uppercase tracking-wide text-wl-text-secondary">Water Source → Reservoir</span>
              <Button variant="secondary" onClick={() => setOpenForm("source")}>Connect</Button>
            </div>
            <LinkTable
              title="" endpointLabel="Source → Reservoir" timezone={farm?.timezone} closing={closingId}
              onClose={(id) => close("source", id)}
              rows={(sourceLinks.data ?? []).map((l) => ({
                id: l.id, effective_from: l.effective_from, effective_to: l.effective_to, reason: l.reason,
                endpoint: `${sourceById.get(l.water_source_id ?? "")?.code ?? "—"} → ${reservoirById.get(l.reservoir_id ?? "")?.code ?? "—"}`,
              }))}
            />
          </div>
          <div>
            <div className="mb-2 flex items-center justify-between">
              <span className="text-xs font-semibold uppercase tracking-wide text-wl-text-secondary">Reservoir → Irrigation Circuit</span>
              <Button variant="secondary" onClick={() => setOpenForm("circuit")}>Connect</Button>
            </div>
            <LinkTable
              title="" endpointLabel="Reservoir → Circuit" timezone={farm?.timezone} closing={closingId}
              onClose={(id) => close("circuit", id)}
              rows={(circuitLinks.data ?? []).map((l) => ({
                id: l.id, effective_from: l.effective_from, effective_to: l.effective_to, reason: l.reason,
                endpoint: `${reservoirById.get(l.reservoir_id ?? "")?.code ?? "—"} → ${circuitById.get(l.irrigation_circuit_id ?? "")?.code ?? "—"}`,
              }))}
            />
          </div>
          <div>
            <div className="mb-2 flex items-center justify-between">
              <span className="text-xs font-semibold uppercase tracking-wide text-wl-text-secondary">Irrigation Circuit → Delivery Point</span>
              <Button variant="secondary" onClick={() => setOpenForm("delivery")}>Connect</Button>
            </div>
            <LinkTable
              title="" endpointLabel="Circuit → Delivery Point" timezone={farm?.timezone} closing={closingId}
              onClose={(id) => close("delivery", id)}
              rows={(deliveryLinks.data ?? []).map((l) => ({
                id: l.id, effective_from: l.effective_from, effective_to: l.effective_to, reason: l.reason,
                endpoint: `${circuitById.get(l.irrigation_circuit_id ?? "")?.code ?? "—"} → ${deliveryPointById.get(l.water_delivery_point_id ?? "")?.code ?? "—"}`,
              }))}
            />
          </div>
          <div>
            <div className="mb-2 flex items-center justify-between">
              <span className="text-xs font-semibold uppercase tracking-wide text-wl-text-secondary">Return Point → Return Reservoir</span>
              <Button variant="secondary" onClick={() => setOpenForm("return")}>Connect</Button>
            </div>
            <LinkTable
              title="" endpointLabel="Return Point → Return Reservoir" timezone={farm?.timezone} closing={closingId}
              onClose={(id) => close("return", id)}
              rows={(returnLinks.data ?? []).map((l) => ({
                id: l.id, effective_from: l.effective_from, effective_to: l.effective_to, reason: l.reason,
                endpoint: `${returnPointById.get(l.water_return_point_id ?? "")?.code ?? "—"} → ${reservoirById.get(l.return_reservoir_id ?? "")?.code ?? "—"}`,
              }))}
            />
          </div>
        </div>
      )}
    </section>
  );
}
