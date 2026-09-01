"use client";

import { useParams } from "next/navigation";
import { useState } from "react";

import { Breadcrumbs } from "@/components/Breadcrumbs";
import { ProductionTransferForm } from "@/components/leafy/ProductionTransferForm";
import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/components/ui/Button";
import type { LeafyProductionTransferRead } from "@/lib/api/client";
import { AppError } from "@/lib/errors/adapter";
import { useRecordLeafyProductionTransfer } from "@/lib/query/hooks";

function asAppError(error: unknown): AppError {
  return error instanceof AppError ? error : new AppError("server_error", "Something went wrong. Please try again.");
}

type SuccessResult = { transfer: LeafyProductionTransferRead; tableLabelById: Record<string, string> };

/** NURSERY-OPS-005B: the Leafy Production Transfer operator workspace --
 * Nursery Cultivation Plate source(s) to Production Cultivation Plate(s)
 * on Leafy Table(s), one atomic composite command. One transaction
 * workspace (configure -> review -> confirm), matching the established
 * InterSalads/Sowing/Seedling pattern -- not a wizard, no list view (this
 * page's whole purpose is completing the next transfer). Never claims the
 * Batch is "eligible for Production" on success (section 35, frozen): this
 * page does not own the global stage-transition decision, and one transfer
 * command may not resolve every pre-production source -- the success
 * screen states only this command's own authoritative source-remaining
 * counts. */
export default function ProductionTransferPage() {
  const { farmId } = useParams<{ farmId: string }>();
  const [formKey, setFormKey] = useState(0);
  const [restrictToBatchId, setRestrictToBatchId] = useState<string | undefined>(undefined);
  const [serverError, setServerError] = useState<AppError | null>(null);
  const [success, setSuccess] = useState<SuccessResult | null>(null);

  const mutation = useRecordLeafyProductionTransfer(farmId);

  function startNew(batchId?: string) {
    setSuccess(null);
    setServerError(null);
    setRestrictToBatchId(batchId);
    setFormKey((k) => k + 1);
  }

  return (
    <div>
      <PageHeader
        title="Production Transfer"
        breadcrumbs={
          <Breadcrumbs
            items={[
              { label: "Home", href: `/farms/${farmId}` },
              { label: "Production Operations" },
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
              <dt className="text-ink-muted">Batch</dt>
              <dd className="font-medium text-ink">{success.transfer.batch_code}</dd>
            </div>
            <div>
              <dt className="text-ink-muted">Total transferred</dt>
              <dd className="font-medium text-ink">{success.transfer.total_destination_plant_count.toLocaleString()}</dd>
            </div>
            <div>
              <dt className="text-ink-muted">Destinations</dt>
              <dd className="font-medium text-ink">{success.transfer.destination_lines.length}</dd>
            </div>
          </dl>

          <div>
            <h3 className="text-sm font-semibold text-ink">Sources</h3>
            <ul className="divide-y divide-border-subtle text-sm">
              {success.transfer.source_lines.map((line) => (
                <li key={line.id} className="flex items-center justify-between py-2">
                  <span className="text-ink">{line.carrier.code}</span>
                  <span className="text-ink-muted">
                    {line.remainder_after > 0
                      ? `${line.remainder_after.toLocaleString()} remaining`
                      : "Biologically empty — physical Plate remains at its current location"}
                  </span>
                </li>
              ))}
            </ul>
          </div>

          <div>
            <h3 className="text-sm font-semibold text-ink">Destinations</h3>
            <ul className="divide-y divide-border-subtle text-sm">
              {success.transfer.destination_lines.map((line) => (
                <li key={line.destination_batch_carrier_assignment_id} className="flex items-center justify-between py-2">
                  <span className="text-ink">
                    {line.carrier.code} → {success.tableLabelById[line.destination_location_id] ?? "—"}
                  </span>
                  <span className="text-ink-muted">{line.assigned_plant_count.toLocaleString()} plants</span>
                </li>
              ))}
            </ul>
          </div>

          <div className="flex flex-wrap gap-3">
            <Button type="button" variant="primary" onClick={() => startNew(success.transfer.batch_id)}>
              Continue this Batch
            </Button>
            <Button type="button" variant="secondary" onClick={() => startNew(undefined)}>
              Start new transfer
            </Button>
          </div>
        </div>
      ) : (
        <ProductionTransferForm
          key={formKey}
          farmId={farmId}
          restrictToBatchId={restrictToBatchId}
          isSubmitting={mutation.isPending}
          serverError={serverError}
          onSubmit={(batchId, payload, tableLabelById) => {
            setServerError(null);
            mutation.mutate(
              { batchId, payload },
              {
                onSuccess: (transfer) => setSuccess({ transfer, tableLabelById }),
                onError: (error) => setServerError(asAppError(error)),
              },
            );
          }}
        />
      )}
    </div>
  );
}
