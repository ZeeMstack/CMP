"use client";

import { useState } from "react";

import { Breadcrumbs } from "@/components/Breadcrumbs";
import { ErrorState } from "@/components/ErrorState";
import { LoadingSkeleton } from "@/components/LoadingSkeleton";
import { LabelCard, LabelPrintSheet, LABEL_TEMPLATE_VERSION } from "@/components/labels/LabelCard";
import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/components/ui/Button";
import type { QrEntityType } from "@/lib/api/client";
import { AppError } from "@/lib/errors/adapter";
import { labelContentFor } from "@/lib/labels/labelContent";
import { openLabelPrintWindow } from "@/lib/labels/printableLabel";
import { usePrintQrLabel, useQrIdentifierFor, useResolveQr } from "@/lib/query/hooks";

const ELIGIBLE_ENTITY_TYPES: readonly QrEntityType[] = [
  "crop_batch",
  "location",
  "carrier",
  "asset",
  "batch_carrier_assignment",
  "harvested_produce_lot",
  "graded_produce_lot",
  "finished_goods_lot",
];

function isEligibleEntityType(value: string): value is QrEntityType {
  return (ELIGIBLE_ENTITY_TYPES as readonly string[]).includes(value);
}

function errorMessage(error: unknown): string {
  return error instanceof AppError ? error.message : "Something went wrong. Please try again.";
}

export function LabelPreviewClient({
  farmId,
  entityType,
  entityId,
  canonicalAppOrigin,
}: {
  farmId: string;
  entityType: string;
  entityId: string;
  /** PILOT-SCAN-001 FINAL SECURITY CLOSURE: resolved server-side from
   * `APP_BASE_URL` (see `page.tsx`'s Server Component boundary) -- `null`
   * means the server has no trustworthy canonical origin configured, and
   * this component must refuse to print a QR rather than fall back to
   * `window.location.origin`. */
  canonicalAppOrigin: string | null;
}) {
  const [reprintReason, setReprintReason] = useState("");
  const [printError, setPrintError] = useState<string | null>(null);
  const [lastPrinted, setLastPrinted] = useState<{ isReprint: boolean } | null>(null);

  const validType = isEligibleEntityType(entityType);
  const qrQuery = useQrIdentifierFor(farmId, validType ? entityType : "carrier", validType ? entityId : "");
  const token = qrQuery.data?.token;
  const scanQuery = useResolveQr(token ?? "", Boolean(token));
  const printMutation = usePrintQrLabel(token ?? "");

  if (!validType) {
    return <ErrorState error={new AppError("not_found", "This entity type does not support QR labels.")} />;
  }

  if (!canonicalAppOrigin) {
    return (
      <ErrorState
        error={
          new AppError(
            "server_error",
            "The application's canonical web address is not configured (APP_BASE_URL). A QR label cannot be printed until this is fixed, so a printed label can never point at the wrong host.",
          )
        }
      />
    );
  }

  const isLoading = qrQuery.isLoading || scanQuery.isLoading;
  const loadError = qrQuery.error ?? scanQuery.error;

  return (
    <div>
      <PageHeader
        title="Print Label"
        breadcrumbs={
          <Breadcrumbs items={[{ label: "Home", href: `/farms/${farmId}` }, { label: "Print Label" }]} />
        }
      />

      {isLoading && <LoadingSkeleton rows={4} label="Preparing label" />}
      {loadError && (
        <ErrorState
          error={loadError}
          onRetry={() => {
            qrQuery.refetch();
            scanQuery.refetch();
          }}
        />
      )}

      {!isLoading && !loadError && token && scanQuery.data && (
        <div className="flex flex-col gap-6">
          <div className="rounded-xl border border-wl-border bg-wl-surface-sunken p-6">
            <LabelPrintSheet size={labelContentFor(scanQuery.data).size}>
              <LabelCard token={token} canonicalAppOrigin={canonicalAppOrigin} {...labelContentFor(scanQuery.data)} />
            </LabelPrintSheet>
          </div>

          <div className="flex flex-wrap items-end gap-3 print:hidden">
            <div className="flex flex-col gap-1">
              <label htmlFor="reprint-reason" className="text-sm font-medium text-wl-text">
                Reprint reason (optional)
              </label>
              <input
                id="reprint-reason"
                type="text"
                value={reprintReason}
                onChange={(e) => setReprintReason(e.target.value)}
                placeholder="e.g. label damaged"
                className="h-9 w-64 rounded-md border border-wl-border-strong px-3 text-sm"
              />
            </div>
            <Button
              variant="primary"
              onClick={() => {
                setPrintError(null);
                printMutation.mutate(
                  {
                    template: `${scanQuery.data.entity_type}_${labelContentFor(scanQuery.data).size}`,
                    template_version: LABEL_TEMPLATE_VERSION,
                    reason: reprintReason.trim() || null,
                  },
                  {
                    onSuccess: (result) => {
                      setLastPrinted({ isReprint: result.is_reprint });
                      // PILOT-SCAN-001B: label-only printing -- open the
                      // dedicated print-only document (`/print/labels`)
                      // rather than `window.print()`-ing this page itself,
                      // which would print the surrounding nav/breadcrumbs/
                      // controls along with the label.
                      const content = labelContentFor(scanQuery.data);
                      openLabelPrintWindow([
                        {
                          token,
                          size: content.size,
                          entityTypeLabel: content.entityTypeLabel,
                          code: content.code,
                          lines: content.secondaryLine ? [content.secondaryLine] : [],
                        },
                      ]);
                    },
                    onError: (error) => setPrintError(errorMessage(error)),
                  },
                );
              }}
              disabled={printMutation.isPending}
            >
              {printMutation.isPending ? "Requesting print…" : "Print label"}
            </Button>
            {printError && <p className="text-sm text-danger-700">{printError}</p>}
            {lastPrinted && (
              <p className="text-sm text-wl-text-secondary">
                {lastPrinted.isReprint
                  ? "Reprint requested -- this only records that a print was requested, not that the physical label was produced."
                  : "Print requested -- this only records that a print was requested, not that the physical label was produced."}
              </p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
