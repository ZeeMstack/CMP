"use client";

import { useParams } from "next/navigation";
import { useState } from "react";

import { Breadcrumbs } from "@/components/Breadcrumbs";
import { IntervinesTransplantForm } from "@/components/nursery/IntervinesTransplantForm";
import { NurseryJourney } from "@/components/nursery/NurseryJourney";
import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/components/ui/Button";
import type { IntervinesTransplantRead } from "@/lib/api/client";
import { AppError } from "@/lib/errors/adapter";
import { useIntervinesPlacementGrowCubes, useIntervinesPlacements, useRecordIntervinesTransplant } from "@/lib/query/hooks";

function asAppError(error: unknown): AppError {
  return error instanceof AppError ? error : new AppError("server_error", "Something went wrong. Please try again.");
}

type SuccessResult = { transplant: IntervinesTransplantRead; tableCode: string };

/** VINES-OPS-001A: the InterVines Transplant operator workspace -- Seedling
 * source Tray to a server-allocated pool of Grow Cube(s) on one InterVines
 * Table, one atomic composite command. One transaction workspace (configure
 * -> review -> confirm), matching the established InterSalads pattern.
 * Unlike InterSalads' own page, this one ALSO carries the compact InterVines
 * read view below it (ticket requirement) -- what is currently living in
 * InterVines right now, aggregated by (Batch, Table), never one row per
 * Grow Cube. */
export default function IntervinesTransplantPage() {
  const { farmId } = useParams<{ farmId: string }>();
  const [formKey, setFormKey] = useState(0);
  const [restrictToBatchId, setRestrictToBatchId] = useState<string | undefined>(undefined);
  const [serverError, setServerError] = useState<AppError | null>(null);
  const [success, setSuccess] = useState<SuccessResult | null>(null);

  const mutation = useRecordIntervinesTransplant(farmId);

  function startNew(batchId?: string) {
    setSuccess(null);
    setServerError(null);
    setRestrictToBatchId(batchId);
    setFormKey((k) => k + 1);
  }

  return (
    <div>
      <PageHeader
        title="Transfer to InterVines"
        breadcrumbs={
          <Breadcrumbs
            items={[
              { label: "Home", href: `/farms/${farmId}` },
              { label: "Nursery Operations" },
              { label: "Transfer to InterVines" },
            ]}
          />
        }
      />
      <NurseryJourney farmId={farmId} current="intervines" />

      {success ? (
        <div className="flex flex-col gap-4 rounded-xl border border-border-subtle bg-surface p-4">
          <h2 className="font-serif text-base font-semibold text-ink">Transfer recorded</h2>
          <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm sm:grid-cols-3">
            <div>
              <dt className="text-ink-muted">Plants transferred</dt>
              <dd className="font-medium text-ink">{success.transplant.plant_count.toLocaleString()}</dd>
            </div>
            <div>
              <dt className="text-ink-muted">Grow Cubes occupied</dt>
              <dd className="font-medium text-ink">{success.transplant.grow_cubes.length.toLocaleString()}</dd>
            </div>
            <div>
              <dt className="text-ink-muted">Batch</dt>
              <dd className="font-medium text-ink">{success.transplant.batch_code}</dd>
            </div>
            <div>
              <dt className="text-ink-muted">InterVines Table</dt>
              <dd className="font-medium text-ink">{success.tableCode}</dd>
            </div>
          </dl>

          <details>
            <summary className="cursor-pointer text-sm font-medium text-ink">
              Assigned Grow Cube codes ({success.transplant.grow_cubes.length})
            </summary>
            <ul className="mt-2 grid grid-cols-2 gap-1 text-xs text-ink-muted sm:grid-cols-4">
              {success.transplant.grow_cubes.map((gc) => (
                <li key={gc.carrier.id}>{gc.carrier.code}</li>
              ))}
            </ul>
          </details>

          <div className="flex flex-wrap gap-3">
            <Button type="button" variant="primary" onClick={() => startNew(success.transplant.batch_id)}>
              Continue this Batch
            </Button>
            <Button type="button" variant="secondary" onClick={() => startNew(undefined)}>
              Start new transfer
            </Button>
          </div>
        </div>
      ) : (
        <IntervinesTransplantForm
          key={formKey}
          farmId={farmId}
          restrictToBatchId={restrictToBatchId}
          isSubmitting={mutation.isPending}
          serverError={serverError}
          onSubmit={(batchId, payload, tableCode) => {
            setServerError(null);
            mutation.mutate(
              { batchId, payload },
              {
                onSuccess: (transplant) => setSuccess({ transplant, tableCode }),
                onError: (error) => setServerError(asAppError(error)),
              },
            );
          }}
        />
      )}

      <div className="mt-8">
        <h2 className="font-serif text-base font-semibold text-ink">Currently in InterVines</h2>
        <IntervinesPlacementsTable farmId={farmId} />
      </div>
    </div>
  );
}

function IntervinesPlacementsTable({ farmId }: { farmId: string }) {
  const placementsQuery = useIntervinesPlacements(farmId);
  const [expanded, setExpanded] = useState<{ batchId: string; tableId: string } | null>(null);

  if (placementsQuery.isLoading) {
    return <p className="mt-2 text-sm text-ink-muted">Loading…</p>;
  }
  const rows = placementsQuery.data ?? [];
  if (rows.length === 0) {
    return <p className="mt-2 text-sm text-ink-muted">Nothing is currently in InterVines.</p>;
  }

  return (
    <div className="mt-2 overflow-x-auto rounded-xl border border-border-subtle bg-surface">
      <table className="w-full min-w-[640px] text-left text-sm">
        <thead>
          <tr className="border-b border-border-subtle text-ink-muted">
            <th className="p-3 font-medium">Batch</th>
            <th className="p-3 font-medium">Crop</th>
            <th className="p-3 font-medium">Variety</th>
            <th className="p-3 font-medium">Table</th>
            <th className="p-3 font-medium">Plants</th>
            <th className="p-3 font-medium">Days in InterVines</th>
            <th className="p-3 font-medium" />
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const key = `${row.batch_id}:${row.table_id}`;
            const isExpanded = expanded?.batchId === row.batch_id && expanded?.tableId === row.table_id;
            return (
              <>
                <tr key={key} className="border-b border-border-subtle last:border-0">
                  <td className="p-3 text-ink">{row.batch_code}</td>
                  <td className="p-3 text-ink">{row.crop_common_name}</td>
                  <td className="p-3 text-ink">{row.variety_name ?? "—"}</td>
                  <td className="p-3 text-ink">{row.table_code}</td>
                  <td className="p-3 text-ink">{row.plant_count.toLocaleString()}</td>
                  <td className="p-3 text-ink">{row.days_in_intervines}</td>
                  <td className="p-3">
                    <button
                      type="button"
                      onClick={() => setExpanded(isExpanded ? null : { batchId: row.batch_id, tableId: row.table_id })}
                      className="min-h-9 rounded-md border border-border-subtle px-3 text-xs font-medium text-ink hover:bg-surface-subtle"
                    >
                      {isExpanded ? "Hide Grow Cubes" : "Grow Cubes"}
                    </button>
                  </td>
                </tr>
                {isExpanded && (
                  <tr key={`${key}-detail`} className="border-b border-border-subtle bg-surface-subtle last:border-0">
                    <td colSpan={7} className="p-3">
                      <GrowCubeDrillDown farmId={farmId} batchId={row.batch_id} tableId={row.table_id} />
                    </td>
                  </tr>
                )}
              </>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function GrowCubeDrillDown({ farmId, batchId, tableId }: { farmId: string; batchId: string; tableId: string }) {
  const detailQuery = useIntervinesPlacementGrowCubes(farmId, batchId, tableId);
  if (detailQuery.isLoading) return <p className="text-xs text-ink-muted">Loading Grow Cubes…</p>;
  const cubes = detailQuery.data ?? [];
  return (
    <ul className="grid grid-cols-2 gap-1 text-xs text-ink-muted sm:grid-cols-4 lg:grid-cols-6">
      {cubes.map((c) => (
        <li key={c.carrier.id}>{c.carrier.code}</li>
      ))}
    </ul>
  );
}
