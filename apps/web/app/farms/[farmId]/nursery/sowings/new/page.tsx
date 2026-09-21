"use client";

import { useParams, useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";

import { Breadcrumbs } from "@/components/Breadcrumbs";
import { NurseryJourney } from "@/components/nursery/NurseryJourney";
import { PageHeader } from "@/components/PageHeader";
import { SowingForm } from "@/components/nursery/SowingForm";
import { Button } from "@/components/ui/Button";
import type { SowingEventRead } from "@/lib/api/client";
import { AppError } from "@/lib/errors/adapter";
import { formatDateTime } from "@/lib/format/datetime";
import { batchMasterLabel, sowingTrayLabel } from "@/lib/labels/operationalLabel";
import { printLabels } from "@/lib/labels/printableLabel";
import { usePreparedPrintLabels } from "@/lib/labels/usePreparedPrintLabels";
import { useSowNewBatch } from "@/lib/query/hooks";

/** PILOT-SCAN-001B: Sowing success is now an inline receipt (not an
 * immediate redirect) so "Print Batch Label" / "Print Tray Labels" have
 * somewhere to live -- the ticket's own mandatory entry point for this
 * screen. "Continue" still takes the operator to the Batch detail page
 * exactly where the old redirect did. */
export function SowingReceipt({ farmId, result }: { farmId: string; result: SowingEventRead }) {
  const router = useRouter();

  const batchLabelSpecs = [
    { entityType: "crop_batch" as const, entityId: result.batch_id, ...batchMasterLabel({ batchCode: result.batch_code }) },
  ];
  // PILOT-SCAN-001B FINAL CLOSURE: the Operational Placement Label's QR
  // identifies the stable Batch Carrier Assignment ("placement") this
  // Sowing line itself just opened -- never the Carrier's own permanent
  // identity. That Carrier (Seed Tray) can later be reused for a different
  // Batch; a placement QR must keep resolving THIS Batch's original
  // placement even after that reuse, never silently become the new
  // occupant. `SowingEventLineRead.batch_carrier_assignment_id` is the
  // exact stable identity this event's own result already returns.
  const trayLabelSpecs = result.lines.map((line) => ({
    entityType: "batch_carrier_assignment" as const,
    entityId: line.batch_carrier_assignment_id,
    ...sowingTrayLabel({ batchCode: result.batch_code, trayCode: line.carrier.code }),
  }));

  const batchLabels = usePreparedPrintLabels(farmId, batchLabelSpecs);
  const trayLabels = usePreparedPrintLabels(farmId, trayLabelSpecs);

  return (
    <div className="flex flex-col gap-6">
      <div className="rounded-xl border border-wl-border bg-wl-surface-raised p-5">
        <p className="text-sm font-medium text-wl-text">
          Sowing recorded for Batch <span className="font-mono">{result.batch_code}</span> --{" "}
          {result.total_seeds_sown} seeds across {result.lines.length}{" "}
          {result.lines.length === 1 ? "tray" : "trays"}.
        </p>
        {/* HOTFIX (sowing effective-time clock skew): the actual
            server-authoritative recorded time, never the pre-save
            browser-generated estimate the Review step showed. */}
        <p className="mt-1 text-sm text-wl-text-secondary">Occurred at {formatDateTime(result.effective_time)}</p>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <Button
          variant="secondary"
          disabled={!batchLabels.labels || batchLabels.labels.length === 0}
          onClick={() => batchLabels.labels && printLabels(batchLabels.labels)}
        >
          {batchLabels.labels ? "Print Batch Label" : "Preparing Batch Label…"}
        </Button>
        <Button
          variant="secondary"
          disabled={!trayLabels.labels || trayLabels.labels.length === 0}
          onClick={() => trayLabels.labels && printLabels(trayLabels.labels)}
        >
          {trayLabels.labels ? `Print Tray Labels (${trayLabels.labels.length})` : "Preparing Tray Labels…"}
        </Button>
        <Button variant="primary" onClick={() => router.push(`/farms/${farmId}/crop-batches/${result.batch_id}?tab=sowing`)}>
          Continue
        </Button>
      </div>
      {Boolean(batchLabels.error || trayLabels.error) && (
        <p className="text-sm text-danger-700">Labels could not be prepared. The sowing itself was recorded successfully.</p>
      )}
    </div>
  );
}

export default function NewSowingPage() {
  const { farmId } = useParams<{ farmId: string }>();
  const searchParams = useSearchParams();
  const mutation = useSowNewBatch(farmId);
  const [serverError, setServerError] = useState<string | null>(null);
  const [result, setResult] = useState<SowingEventRead | null>(null);

  // PLANNING-OPS-001: "Sow Now" from a Seeding Program plan line hands off
  // here via query params -- prefill/context only, never a second Sowing
  // form (the ticket explicitly forbids that).
  const seedingProgramLineId = searchParams.get("seeding_program_line_id");
  const planCropId = searchParams.get("crop_id");
  const planVarietyId = searchParams.get("variety_id");
  const planPrefill =
    seedingProgramLineId && planCropId
      ? { seedingProgramLineId, cropId: planCropId, varietyId: planVarietyId }
      : null;

  return (
    <div>
      <PageHeader
        title="New Sowing"
        compact
        breadcrumbs={
          <Breadcrumbs
            items={[
              { label: "Home", href: `/farms/${farmId}` },
              { label: "Nursery Operations" },
              { label: "New Sowing" },
            ]}
          />
        }
      />
      <NurseryJourney farmId={farmId} current="seeding" />
      {result ? (
        <SowingReceipt farmId={farmId} result={result} />
      ) : (
        <SowingForm
          farmId={farmId}
          isSubmitting={mutation.isPending}
          serverError={serverError}
          planPrefill={planPrefill}
          onSubmit={(payload) => {
            setServerError(null);
            mutation.mutate(payload, {
              onSuccess: (sowingResult) => setResult(sowingResult),
              onError: (error) => {
                setServerError(error instanceof AppError ? error.message : "Something went wrong. Please try again.");
              },
            });
          }}
        />
      )}
    </div>
  );
}
