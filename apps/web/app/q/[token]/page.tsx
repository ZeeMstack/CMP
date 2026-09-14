"use client";

import Link from "next/link";
import { useParams } from "next/navigation";

import { ErrorState } from "@/components/ErrorState";
import { LoadingSkeleton } from "@/components/LoadingSkeleton";
import type { ScanContext } from "@/lib/api/client";
import { useResolveQr } from "@/lib/query/hooks";

const ENTITY_TYPE_LABELS: Record<ScanContext["entity_type"], string> = {
  crop_batch: "Batch",
  location: "Location",
  carrier: "Carrier",
  asset: "Asset",
  batch_carrier_assignment: "Placement",
  harvested_produce_lot: "Harvest Lot",
  graded_produce_lot: "Graded Lot",
  finished_goods_lot: "Finished Goods Lot",
};

function VarietyLine({ crop, variety }: { crop: { common_name: string }; variety: { name: string } | null }) {
  return <p className="text-sm text-wl-text-secondary">{variety ? `${crop.common_name} · ${variety.name}` : crop.common_name}</p>;
}

/** WHAT is currently true, resolved fresh at scan time -- never the QR
 * row's own stored data (PILOT-SCAN-001's core rule: the token is an
 * identifier, not a snapshot). Renders per entity_type -- a compact,
 * discriminated switch, never one giant universal block. */
function WhatItRelatesToNow({ ctx }: { ctx: ScanContext }) {
  switch (ctx.entity_type) {
    case "crop_batch":
      return (
        <div className="flex flex-col gap-1">
          <VarietyLine crop={ctx.crop} variety={ctx.variety} />
          <p className="text-sm text-wl-text-secondary">
            Stage: <span className="font-medium text-wl-text">{ctx.current_stage_name}</span> · {ctx.state}
          </p>
          {ctx.placements.length > 0 && (
            <div className="mt-2">
              <p className="text-xs font-semibold uppercase tracking-wide text-wl-text-tertiary">Current placements</p>
              <ul className="mt-1 flex flex-col gap-1">
                {ctx.placements.map((p) => (
                  <li key={p.batch_carrier_assignment_id} className="text-sm text-wl-text">
                    {p.carrier_code}
                    {p.location ? ` — ${p.location.path_string}` : " — location unknown"}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      );
    case "location":
      return (
        <div className="flex flex-col gap-1">
          <p className="text-sm text-wl-text-secondary">{ctx.location.path_string}</p>
          {ctx.occupants.length > 0 ? (
            <div className="mt-2">
              <p className="text-xs font-semibold uppercase tracking-wide text-wl-text-tertiary">Current occupants</p>
              <ul className="mt-1 flex flex-col gap-1">
                {ctx.occupants.map((o, i) => (
                  <li key={`${o.kind}-${o.code}-${i}`} className="text-sm text-wl-text">
                    {o.code} <span className="text-wl-text-tertiary">({o.kind})</span>
                  </li>
                ))}
              </ul>
            </div>
          ) : (
            <p className="text-sm text-wl-text-tertiary">No current occupants.</p>
          )}
        </div>
      );
    case "carrier":
      return (
        <div className="flex flex-col gap-1">
          <p className="text-sm text-wl-text-secondary">{ctx.carrier_type_name}</p>
          <p className="text-sm">
            <span className="text-wl-text-tertiary">Current crop: </span>
            {ctx.current_batch ? (
              <span className="font-medium text-wl-text">
                {ctx.current_batch.code}
                {ctx.current_batch.variety ? ` · ${ctx.current_batch.variety.name}` : ` · ${ctx.current_batch.crop.common_name}`}
              </span>
            ) : (
              <span className="text-wl-text-tertiary">none</span>
            )}
          </p>
          <p className="text-sm">
            <span className="text-wl-text-tertiary">Current location: </span>
            {ctx.current_location ? (
              <span className="font-medium text-wl-text">{ctx.current_location.path_string}</span>
            ) : (
              <span className="text-amber-700">{ctx.unresolved_reason ?? "unknown"}</span>
            )}
          </p>
        </div>
      );
    case "asset":
      return (
        <div className="flex flex-col gap-1">
          <p className="text-sm text-wl-text-secondary">{ctx.asset_type_name}</p>
          <p className="text-sm">
            <span className="text-wl-text-tertiary">Current location: </span>
            {ctx.current_location ? (
              <span className="font-medium text-wl-text">{ctx.current_location.path_string}</span>
            ) : (
              <span className="text-amber-700">{ctx.unresolved_reason ?? "unknown"}</span>
            )}
          </p>
        </div>
      );
    case "batch_carrier_assignment":
      return (
        <div className="flex flex-col gap-1">
          <VarietyLine crop={ctx.batch.crop} variety={ctx.batch.variety} />
          <p className="text-sm text-wl-text-secondary">Carrier: {ctx.carrier_code}</p>
          <p className="text-sm">
            <span className="text-wl-text-tertiary">Current location: </span>
            {ctx.current_location ? (
              <span className="font-medium text-wl-text">{ctx.current_location.path_string}</span>
            ) : (
              <span className="text-amber-700">{ctx.unresolved_reason ?? "unknown"}</span>
            )}
          </p>
          {ctx.released && <p className="text-sm text-wl-text-tertiary">This placement has been released.</p>}
        </div>
      );
    case "harvested_produce_lot":
      return (
        <div className="flex flex-col gap-1">
          <VarietyLine crop={ctx.batch.crop} variety={ctx.batch.variety} />
          <p className="text-sm text-wl-text-secondary">From Batch {ctx.batch.code}</p>
          <p className="text-sm text-wl-text-secondary">
            {ctx.total_harvested_weight_kg} kg{ctx.total_whole_unit_count ? ` · ${ctx.total_whole_unit_count} units` : ""}
          </p>
        </div>
      );
    case "graded_produce_lot":
      return (
        <div className="flex flex-col gap-1">
          <VarietyLine crop={ctx.crop} variety={ctx.variety} />
          <p className="text-sm text-wl-text-secondary">From Harvest Lot {ctx.source_harvested_produce_lot_code}</p>
          <p className="text-sm text-wl-text-secondary">{ctx.original_received_weight_kg} kg</p>
        </div>
      );
    case "finished_goods_lot":
      return (
        <div className="flex flex-col gap-1">
          <VarietyLine crop={ctx.crop} variety={ctx.variety} />
          <p className="text-sm text-wl-text-secondary">
            {ctx.net_packed_weight_kg} kg · {ctx.package_count} packages
          </p>
        </div>
      );
  }
}

export default function ScanPage() {
  const { token } = useParams<{ token: string }>();
  const scanQuery = useResolveQr(token);

  return (
    <div className="mx-auto flex max-w-lg flex-col gap-6 px-4 py-8">
      <div className="text-center">
        <p className="text-xs font-semibold uppercase tracking-wide text-wl-text-tertiary">growCMP</p>
      </div>

      {scanQuery.isLoading && <LoadingSkeleton rows={5} label="Resolving scanned code" />}

      {/* A failed read is NEVER rendered as "not assigned / empty" -- it is
       * always a distinct error state, so an operator never mistakes a
       * network/permission failure for a genuinely empty entity. */}
      {scanQuery.error && <ErrorState error={scanQuery.error} onRetry={() => scanQuery.refetch()} />}

      {!scanQuery.isLoading && !scanQuery.error && scanQuery.data && (
        <div className="flex flex-col gap-6">
          <div className="rounded-xl border border-wl-border bg-wl-surface-raised p-5">
            <p className="text-xs font-semibold uppercase tracking-wide text-wl-text-tertiary">
              {ENTITY_TYPE_LABELS[scanQuery.data.entity_type]}
            </p>
            <h1 className="font-mono text-2xl font-bold leading-tight text-wl-text">{scanQuery.data.code}</h1>
            <div className="mt-3 border-t border-wl-border pt-3">
              <WhatItRelatesToNow ctx={scanQuery.data} />
            </div>
          </div>

          {(scanQuery.data.work_items ?? []).length > 0 && (
            <div className="rounded-xl border border-wl-border bg-wl-surface-raised p-5">
              <p className="text-xs font-semibold uppercase tracking-wide text-wl-text-tertiary">Related work</p>
              <ul className="mt-2 flex flex-col gap-2">
                {(scanQuery.data.work_items ?? []).map((item) => (
                  <li key={item.id} className="flex items-center justify-between gap-2 text-sm">
                    <span className="min-w-0 truncate text-wl-text">{item.title}</span>
                    <span className="shrink-0 text-xs uppercase text-wl-text-tertiary">{item.status}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {(scanQuery.data.actions ?? []).length > 0 && (
            <div className="flex flex-col gap-2">
              {(scanQuery.data.actions ?? []).map((action) => (
                <Link
                  key={action.href}
                  href={action.href}
                  className="flex min-h-11 items-center justify-center rounded-lg border border-wl-border-strong bg-wl-surface-raised px-4 text-sm font-medium text-wl-text hover:bg-wl-surface-hover focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-wl-focus"
                >
                  {action.label}
                </Link>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
