"use client";

import { useParams } from "next/navigation";
import { useState } from "react";

import { Breadcrumbs } from "@/components/Breadcrumbs";
import { IntersaladsTransplantForm } from "@/components/nursery/IntersaladsTransplantForm";
import { NurseryJourney } from "@/components/nursery/NurseryJourney";
import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/components/ui/Button";
import type { IntersaladsTransplantRead } from "@/lib/api/client";
import { AppError } from "@/lib/errors/adapter";
import { useRecordIntersaladsTransplant } from "@/lib/query/hooks";

function asAppError(error: unknown): AppError {
  return error instanceof AppError ? error : new AppError("server_error", "Something went wrong. Please try again.");
}

type SuccessResult = { transplant: IntersaladsTransplantRead; tableCodeById: Record<string, string> };

/** NURSERY-OPS-004B.2: the InterSalads Transplant operator workspace --
 * Seedling source Tray(s) to Nursery Cultivation Plate(s) on InterSalads
 * Table(s), one atomic composite command (NURSERY-OPS-004B.1). One
 * transaction workspace (configure -> review -> confirm), not a wizard --
 * matches the established Sowing/Seedling form pattern. No list view: this
 * page's whole purpose is completing the next transplant, not browsing past
 * ones (section 42/56 -- a history panel was explicitly out of MVP scope). */
export default function IntersaladsTransplantPage() {
  const { farmId } = useParams<{ farmId: string }>();
  const [formKey, setFormKey] = useState(0);
  const [restrictToBatchId, setRestrictToBatchId] = useState<string | undefined>(undefined);
  const [serverError, setServerError] = useState<AppError | null>(null);
  const [success, setSuccess] = useState<SuccessResult | null>(null);

  const mutation = useRecordIntersaladsTransplant(farmId);

  function startNew(batchId?: string) {
    setSuccess(null);
    setServerError(null);
    setRestrictToBatchId(batchId);
    setFormKey((k) => k + 1);
  }

  return (
    <div>
      <PageHeader
        title="Transfer to Inter Leafy Greens"
        breadcrumbs={
          <Breadcrumbs
            items={[
              { label: "Home", href: `/farms/${farmId}` },
              { label: "Batches", href: `/farms/${farmId}/crop-batches` },
              { label: "Transfer to Inter Leafy Greens" },
            ]}
          />
        }
      />
      <NurseryJourney farmId={farmId} current="intersalads" />

      {success ? (
        <div className="flex flex-col gap-4 rounded-xl border border-border-subtle bg-surface p-4">
          <h2 className="font-serif text-base font-semibold text-ink">Transplant recorded</h2>
          <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm sm:grid-cols-3">
            <div>
              <dt className="text-ink-muted">Batch</dt>
              <dd className="font-medium text-ink">{success.transplant.batch_code}</dd>
            </div>
            <div>
              <dt className="text-ink-muted">Total transplanted</dt>
              <dd className="font-medium text-ink">{success.transplant.total_destination_plant_count.toLocaleString()}</dd>
            </div>
            <div>
              <dt className="text-ink-muted">Destinations</dt>
              <dd className="font-medium text-ink">{success.transplant.destination_lines.length}</dd>
            </div>
          </dl>

          <div>
            <h3 className="text-sm font-semibold text-ink">Sources</h3>
            <ul className="divide-y divide-border-subtle text-sm">
              {success.transplant.source_lines.map((line) => (
                <li key={line.id} className="flex items-center justify-between py-2">
                  <span className="text-ink">{line.carrier.code}</span>
                  <span className="text-ink-muted">
                    {line.remainder_after > 0
                      ? `${line.remainder_after.toLocaleString()} seedlings remaining`
                      : "Source completed — 0 seedlings remaining"}
                  </span>
                </li>
              ))}
            </ul>
          </div>

          <div>
            <h3 className="text-sm font-semibold text-ink">Destinations</h3>
            <ul className="divide-y divide-border-subtle text-sm">
              {success.transplant.destination_lines.map((line) => (
                <li key={line.destination_batch_carrier_assignment_id} className="flex items-center justify-between py-2">
                  <span className="text-ink">
                    {line.carrier.code} → {success.tableCodeById[line.destination_location_id] ?? "—"}
                  </span>
                  <span className="text-ink-muted">{line.assigned_plant_count.toLocaleString()} seedlings</span>
                </li>
              ))}
            </ul>
          </div>

          <div className="flex flex-wrap gap-3">
            <Button type="button" variant="primary" onClick={() => startNew(success.transplant.batch_id)}>
              Continue this Batch
            </Button>
            <Button type="button" variant="secondary" onClick={() => startNew(undefined)}>
              Start new transplant
            </Button>
          </div>
        </div>
      ) : (
        <IntersaladsTransplantForm
          key={formKey}
          farmId={farmId}
          restrictToBatchId={restrictToBatchId}
          isSubmitting={mutation.isPending}
          serverError={serverError}
          onSubmit={(batchId, payload, tableCodeById) => {
            setServerError(null);
            mutation.mutate(
              { batchId, payload },
              {
                onSuccess: (transplant) => setSuccess({ transplant, tableCodeById }),
                onError: (error) => setServerError(asAppError(error)),
              },
            );
          }}
        />
      )}
    </div>
  );
}
