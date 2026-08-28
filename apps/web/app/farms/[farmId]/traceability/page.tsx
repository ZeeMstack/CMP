"use client";

import { useParams } from "next/navigation";
import { useState } from "react";

import { Breadcrumbs } from "@/components/Breadcrumbs";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { FilterableSelect, type FilterableSelectOption } from "@/components/FilterableSelect";
import { LoadingSkeleton } from "@/components/LoadingSkeleton";
import { PageHeader } from "@/components/PageHeader";
import { TraceFinishedGoodsLotPanel } from "@/components/processing/TraceFinishedGoodsLotPanel";
import { TraceImpactPanel } from "@/components/processing/TraceImpactPanel";
import { TraceListSection } from "@/components/processing/TraceListSection";
import { Tabs } from "@/components/ui/Tabs";
import type { LocationTreeNode } from "@/lib/api/client";
import {
  useCropBatchImpact, useFinishedGoodsLotTrace, useFinishedGoodsLots, useGradedProduceLot, useGradedProduceLots,
  useGradingEvent, useHarvestedProduceLotImpact, useHarvestedProduceLots, useLocationsTree, useOperationalSummary,
} from "@/lib/query/hooks";

type EntryType = "crop-batch" | "hpl" | "gpl" | "fgl";

const ENTRY_TABS = [
  { id: "crop-batch", label: "Crop Batch" },
  { id: "hpl", label: "Harvested Produce Lot" },
  { id: "gpl", label: "Graded Produce Lot" },
  { id: "fgl", label: "Finished Goods Lot" },
] as const;

/** Mirrors `finished-goods/[fgLotId]/page.tsx`'s own `flattenLocationLabels`
 * -- kept as its own local copy rather than an import, since that page
 * belongs to a different UI-OPT-001 batch (Post-Harvest) and this route is
 * a separate, later batch (Dispatch/Traceability/Recall); duplicating six
 * lines is cheaper than coupling the two batches' files together. */
function flattenLocationLabels(nodes: LocationTreeNode[], pathPrefix: string[] = []): Map<string, string> {
  const map = new Map<string, string>();
  for (const node of nodes) {
    const path = [...pathPrefix, node.name];
    map.set(node.id, path.join(" / "));
    for (const [id, label] of flattenLocationLabels(node.children, path)) map.set(id, label);
  }
  return map;
}

function CropBatchResult({ farmId, batchId, locationLabelById }: { farmId: string; batchId: string; locationLabelById: Map<string, string> }) {
  const impactQuery = useCropBatchImpact(farmId, batchId);
  if (impactQuery.isLoading) return <LoadingSkeleton rows={4} label="Loading trace" />;
  if (impactQuery.error) return <ErrorState error={impactQuery.error} onRetry={() => impactQuery.refetch()} />;
  const data = impactQuery.data;
  if (!data) return null;
  return (
    <TraceImpactPanel
      farmId={farmId}
      summary={data.summary}
      completeness={data.completeness}
      produceLots={data.produce_lots}
      packingInputs={data.packing_inputs}
      gradedProduceLots={data.graded_produce_lots}
      finishedGoods={data.finished_goods}
      storage={data.storage}
      dispatches={data.dispatches}
      locationLabelById={locationLabelById}
    >
      <TraceListSection
        title="Harvest events"
        items={data.harvest_events}
        keyFor={(h) => h.harvest_event_id}
        emptyLabel="This Batch has not been harvested yet."
        renderItem={(h) => <span className="text-ink-muted">{new Date(h.effective_time).toLocaleString()}</span>}
      />
      <TraceListSection
        title="Batch lineage"
        items={data.lineage.batches}
        keyFor={(b) => b.batch_id}
        emptyLabel="No related Batches (splits/merges) recorded."
        renderItem={(b) => (
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="font-medium text-ink">{b.code}</span>
            <span className="text-ink-muted">{b.state} — {b.transformation_type}</span>
          </div>
        )}
      />
    </TraceImpactPanel>
  );
}

function HplResult({ farmId, produceLotId, locationLabelById }: { farmId: string; produceLotId: string; locationLabelById: Map<string, string> }) {
  const impactQuery = useHarvestedProduceLotImpact(farmId, produceLotId);
  if (impactQuery.isLoading) return <LoadingSkeleton rows={4} label="Loading trace" />;
  if (impactQuery.error) return <ErrorState error={impactQuery.error} onRetry={() => impactQuery.refetch()} />;
  const data = impactQuery.data;
  if (!data) return null;
  return (
    <TraceImpactPanel
      farmId={farmId}
      summary={data.summary}
      completeness={data.completeness}
      produceLots={data.produce_lots}
      packingInputs={data.packing_inputs}
      gradedProduceLots={data.graded_produce_lots}
      finishedGoods={data.finished_goods}
      storage={data.storage}
      dispatches={data.dispatches}
      locationLabelById={locationLabelById}
    />
  );
}

/** No backend endpoint traces from a Graded Produce Lot directly. This
 * composes one from two reads that already exist: the GPL's own Grading
 * Event (`useGradingEvent`, giving `source_harvested_produce_lot_id`), then
 * the Harvested Produce Lot Impact trace for that source Lot -- the same
 * endpoint `HplResult` above uses. That trace necessarily already covers
 * this Graded Produce Lot and everything downstream of it, so nothing new
 * is invented; the banner below just explains why the operator sees more
 * than the one Lot they searched for. */
function GplResult({ farmId, gplId, locationLabelById }: { farmId: string; gplId: string; locationLabelById: Map<string, string> }) {
  const gplQuery = useGradedProduceLot(farmId, gplId);
  const gradingEventId = gplQuery.data?.grading_event_id ?? null;
  const gradingEventQuery = useGradingEvent(farmId, gradingEventId);
  const sourceHplId = gradingEventQuery.data?.source_harvested_produce_lot_id ?? null;
  const impactQuery = useHarvestedProduceLotImpact(farmId, sourceHplId);

  if (gplQuery.isLoading || gradingEventQuery.isLoading || (Boolean(sourceHplId) && impactQuery.isLoading)) {
    return <LoadingSkeleton rows={4} label="Loading trace" />;
  }
  if (gplQuery.error) return <ErrorState error={gplQuery.error} onRetry={() => gplQuery.refetch()} />;
  if (gradingEventQuery.error) return <ErrorState error={gradingEventQuery.error} onRetry={() => gradingEventQuery.refetch()} />;
  if (impactQuery.error) return <ErrorState error={impactQuery.error} onRetry={() => impactQuery.refetch()} />;
  const data = impactQuery.data;
  if (!data || !gplQuery.data || !gradingEventQuery.data) return null;

  return (
    <div className="flex flex-col gap-4">
      <p className="rounded-md border border-border-subtle bg-surface-subtle px-3 py-2 text-sm text-ink-muted">
        Showing the full downstream trace from <span className="font-medium text-ink">{gradingEventQuery.data.source_produce_lot_code}</span>,
        the Harvested Produce Lot that <span className="font-medium text-ink">{gplQuery.data.code}</span> was graded from —{" "}
        <span className="font-medium text-ink">{gplQuery.data.code}</span> itself appears in the Graded Produce Lots section below.
      </p>
      <TraceImpactPanel
        farmId={farmId}
        summary={data.summary}
        completeness={data.completeness}
        produceLots={data.produce_lots}
        packingInputs={data.packing_inputs}
        gradedProduceLots={data.graded_produce_lots}
        finishedGoods={data.finished_goods}
        storage={data.storage}
        dispatches={data.dispatches}
        locationLabelById={locationLabelById}
      />
    </div>
  );
}

function FglResult({ farmId, fgLotId, locationLabelById }: { farmId: string; fgLotId: string; locationLabelById: Map<string, string> }) {
  const traceQuery = useFinishedGoodsLotTrace(farmId, fgLotId);
  if (traceQuery.isLoading) return <LoadingSkeleton rows={4} label="Loading trace" />;
  if (traceQuery.error) return <ErrorState error={traceQuery.error} onRetry={() => traceQuery.refetch()} />;
  if (!traceQuery.data) return null;
  return <TraceFinishedGoodsLotPanel farmId={farmId} data={traceQuery.data} locationLabelById={locationLabelById} />;
}

/** UI-OPT-001: Traceability -- lets an operator start a read-only trace
 * from any of the four required entry points (Crop Batch, Harvested
 * Produce Lot, Graded Produce Lot, Finished Goods Lot) and see everything
 * connected to it, forward or backward, using only reads the backend
 * already exposed (see `lib/api/client.ts`'s traceability functions).
 * No mutation controls anywhere on this page. */
export default function TraceabilityPage() {
  const { farmId } = useParams<{ farmId: string }>();
  const [entryType, setEntryType] = useState<EntryType>("crop-batch");
  const [selectedId, setSelectedId] = useState("");

  const batchesQuery = useOperationalSummary(farmId, "all");
  const hplsQuery = useHarvestedProduceLots(farmId);
  const gplsQuery = useGradedProduceLots(farmId);
  const fglsQuery = useFinishedGoodsLots(farmId);
  const locationsQuery = useLocationsTree(farmId);
  const locationLabelById = locationsQuery.data ? flattenLocationLabels(locationsQuery.data) : new Map<string, string>();

  const pickers: Record<EntryType, { options: FilterableSelectOption[]; loading: boolean; placeholder: string }> = {
    "crop-batch": {
      options: (batchesQuery.data ?? []).map((b) => ({ value: b.id, label: b.code, description: b.crop.common_name })),
      loading: batchesQuery.isLoading,
      placeholder: "Search by Batch code…",
    },
    hpl: {
      options: (hplsQuery.data ?? []).map((l) => ({ value: l.id, label: l.code, description: `${l.crop.common_name}${l.variety ? ` / ${l.variety.name}` : ""}` })),
      loading: hplsQuery.isLoading,
      placeholder: "Search by Harvested Produce Lot code…",
    },
    gpl: {
      options: (gplsQuery.data ?? []).map((l) => ({ value: l.id, label: l.code, description: `${l.crop.common_name}${l.variety ? ` / ${l.variety.name}` : ""}` })),
      loading: gplsQuery.isLoading,
      placeholder: "Search by Graded Produce Lot code…",
    },
    fgl: {
      options: (fglsQuery.data ?? []).map((l) => ({ value: l.id, label: l.code, description: `${l.crop.common_name}${l.variety ? ` / ${l.variety.name}` : ""}` })),
      loading: fglsQuery.isLoading,
      placeholder: "Search by Finished Goods Lot code…",
    },
  };
  const activePicker = pickers[entryType];

  return (
    <div>
      <PageHeader
        title="Traceability"
        breadcrumbs={
          <Breadcrumbs items={[{ label: "Home", href: `/farms/${farmId}` }, { label: "Traceability" }]} />
        }
      />

      <div className="mb-6">
        <Tabs
          tabs={ENTRY_TABS.map(({ id, label }) => ({ id, label }))}
          activeId={entryType}
          onChange={(id) => {
            setEntryType(id as EntryType);
            setSelectedId("");
          }}
          aria-label="Trace entry point"
        />
      </div>

      <div className="mb-4 max-w-md">
        <FilterableSelect
          options={activePicker.options}
          value={selectedId}
          onChange={setSelectedId}
          loading={activePicker.loading}
          placeholder={activePicker.placeholder}
          emptyMessage="Nothing available yet in this Farm."
          aria-label={`Select ${ENTRY_TABS.find((t) => t.id === entryType)?.label}`}
        />
      </div>

      {!selectedId && (
        <EmptyState
          title="Start a trace"
          description="Pick a Crop Batch, Harvested Produce Lot, Graded Produce Lot, or Finished Goods Lot above to see everything connected to it."
        />
      )}

      {selectedId && entryType === "crop-batch" && (
        <CropBatchResult farmId={farmId} batchId={selectedId} locationLabelById={locationLabelById} />
      )}
      {selectedId && entryType === "hpl" && (
        <HplResult farmId={farmId} produceLotId={selectedId} locationLabelById={locationLabelById} />
      )}
      {selectedId && entryType === "gpl" && (
        <GplResult farmId={farmId} gplId={selectedId} locationLabelById={locationLabelById} />
      )}
      {selectedId && entryType === "fgl" && (
        <FglResult farmId={farmId} fgLotId={selectedId} locationLabelById={locationLabelById} />
      )}
    </div>
  );
}
