"use client";

import { useParams } from "next/navigation";
import { useState } from "react";

import { Breadcrumbs } from "@/components/Breadcrumbs";
import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/components/ui/Button";
import { VinesProductionTransferForm } from "@/components/vines/VinesProductionTransferForm";
import type { VinesProductionTransferRead } from "@/lib/api/client";
import { AppError } from "@/lib/errors/adapter";
import { vinesProductionPlacementLabel } from "@/lib/labels/operationalLabel";
import { printLabels } from "@/lib/labels/printableLabel";
import { usePreparedPrintLabels } from "@/lib/labels/usePreparedPrintLabels";
import { useRecordVinesProductionTransfer } from "@/lib/query/hooks";

function asAppError(error: unknown): AppError {
  return error instanceof AppError ? error : new AppError("server_error", "Something went wrong. Please try again.");
}

type SuccessResult = { transfer: VinesProductionTransferRead; gutterCode: string };

/** VINES-OPS-001B: the Vines Production Transfer operator workspace --
 * InterVines Grow Cube(s) (retained, still traceable) to a server-allocated
 * pool of Grow Bag(s) on one Grow Gutter, one atomic composite command. One
 * transaction workspace (configure -> review -> confirm), matching the
 * established InterVines/Leafy Production pattern. */
export default function VinesProductionTransferPage() {
  const { farmId } = useParams<{ farmId: string }>();
  const [formKey, setFormKey] = useState(0);
  const [serverError, setServerError] = useState<AppError | null>(null);
  const [success, setSuccess] = useState<SuccessResult | null>(null);

  const mutation = useRecordVinesProductionTransfer(farmId);

  // PILOT-SCAN-001B: `gutterCode` is the only destination-location fact
  // this command's own response exposes (no Greenhouse/Zone/Span
  // breakdown, and no per-bag link back to a specific source Grow Cube --
  // see docs/product/OPEN_QUESTIONS.md) -- the label uses exactly what is
  // authoritatively available (Batch, Grow Bag, Gutter, plant count),
  // never a guessed/invented location breadcrumb.
  // PILOT-SCAN-001B FINAL CLOSURE: QR identifies the destination Batch
  // Carrier Assignment this transfer line itself just opened, not the
  // Grow Bag's own permanent identity -- see the identical rationale in
  // `sowings/new/page.tsx`.
  const placementLabelSpecs = success
    ? success.transfer.grow_bags.map((gb) => ({
        entityType: "batch_carrier_assignment" as const,
        entityId: gb.destination_batch_carrier_assignment_id,
        ...vinesProductionPlacementLabel({
          batchCode: success.transfer.batch_code,
          carrierCode: gb.grow_bag.code,
          gutterCode: success.gutterCode,
          plantCount: gb.assigned_plant_count,
        }),
      }))
    : [];
  const placementLabels = usePreparedPrintLabels(farmId, placementLabelSpecs);

  function startNew() {
    setSuccess(null);
    setServerError(null);
    setFormKey((k) => k + 1);
  }

  return (
    <div>
      <PageHeader
        compact
        title="Transfer to Production"
        breadcrumbs={
          <Breadcrumbs
            items={[
              { label: "Home", href: `/farms/${farmId}` },
              { label: "Vines Production" },
              { label: "Transfer to Production" },
            ]}
          />
        }
      />

      {success ? (
        <div className="flex flex-col gap-4 rounded-xl border border-border-subtle bg-surface p-4">
          <h2 className="font-serif text-base font-semibold text-ink">Transfer recorded</h2>
          <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm sm:grid-cols-3">
            <div>
              <dt className="text-ink-muted">Plants transferred</dt>
              <dd className="font-medium text-ink">{success.transfer.plant_count.toLocaleString()}</dd>
            </div>
            <div>
              <dt className="text-ink-muted">Grow Cubes retained</dt>
              <dd className="font-medium text-ink">{success.transfer.source_grow_cubes.length.toLocaleString()}</dd>
            </div>
            <div>
              <dt className="text-ink-muted">Grow Bags used</dt>
              <dd className="font-medium text-ink">{success.transfer.grow_bags.length.toLocaleString()}</dd>
            </div>
            <div>
              <dt className="text-ink-muted">Batch</dt>
              <dd className="font-medium text-ink">{success.transfer.batch_code}</dd>
            </div>
            <div>
              <dt className="text-ink-muted">Grow Gutter</dt>
              <dd className="font-medium text-ink">{success.gutterCode}</dd>
            </div>
          </dl>

          <details>
            <summary className="cursor-pointer text-sm font-medium text-ink">
              Assigned Grow Bag codes ({success.transfer.grow_bags.length})
            </summary>
            <ul className="mt-2 grid grid-cols-2 gap-1 text-xs text-ink-muted sm:grid-cols-4">
              {success.transfer.grow_bags.map((gb) => (
                <li key={gb.grow_bag.id}>
                  {gb.grow_bag.code} ({gb.assigned_plant_count})
                </li>
              ))}
            </ul>
          </details>

          <div className="flex flex-wrap gap-3">
            <Button
              type="button"
              variant="secondary"
              disabled={!placementLabels.labels || placementLabels.labels.length === 0}
              onClick={() => placementLabels.labels && printLabels(placementLabels.labels)}
            >
              {placementLabels.labels ? `Print Labels (${placementLabels.labels.length})` : "Preparing labels…"}
            </Button>
            <Button type="button" variant="primary" onClick={startNew}>
              Start new transfer
            </Button>
          </div>
        </div>
      ) : (
        <VinesProductionTransferForm
          key={formKey}
          farmId={farmId}
          isSubmitting={mutation.isPending}
          serverError={serverError}
          onSubmit={(batchId, payload, gutterCode) => {
            setServerError(null);
            // UX-OPS-001C/R1: the returned promise settles the form's frozen
            // attempt (success clears it; network/5xx keeps it for a
            // byte-identical Retry; a definitive 4xx releases it).
            return mutation.mutateAsync({ batchId, payload }).then(
              (transfer) => setSuccess({ transfer, gutterCode }),
              (error) => {
                const appError = asAppError(error);
                setServerError(appError);
                throw appError;
              },
            );
          }}
        />
      )}
    </div>
  );
}
