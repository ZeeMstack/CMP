"use client";

import { useState } from "react";
import { useParams } from "next/navigation";

import { Breadcrumbs } from "@/components/Breadcrumbs";
import { ErrorState } from "@/components/ErrorState";
import { LoadingSkeleton } from "@/components/LoadingSkeleton";
import { LabelCard, LabelPrintSheet, LABEL_TEMPLATE_VERSION, type LabelSize } from "@/components/labels/LabelCard";
import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/components/ui/Button";
import type { QrEntityType, ScanContext } from "@/lib/api/client";
import { AppError } from "@/lib/errors/adapter";
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

/** PILOT-SCAN-001: label content derived per entity type. Permanent
 * identities (Carrier/Asset/Location) never surface a mutable fact here
 * (current Batch/location/status) -- only their own stable code/name; the
 * scan page (`/q/[token]`) is where those resolve dynamically. Operational
 * identities (Batch/placement/lots) may show stable creation metadata
 * (crop/variety), never current stage/status. */
function labelContentFor(ctx: ScanContext): { size: LabelSize; entityTypeLabel: string; code: string; secondaryLine?: string } {
  switch (ctx.entity_type) {
    case "carrier":
      return { size: "small", entityTypeLabel: "Carrier", code: ctx.code, secondaryLine: ctx.carrier_type_name };
    case "asset":
      return { size: "small", entityTypeLabel: "Asset", code: ctx.code, secondaryLine: ctx.asset_type_name };
    case "location":
      return { size: "small", entityTypeLabel: "Location", code: ctx.location.path_string };
    case "crop_batch":
      return {
        size: "standard",
        entityTypeLabel: "Batch",
        code: ctx.code,
        secondaryLine: ctx.variety ? `${ctx.crop.common_name} · ${ctx.variety.name}` : ctx.crop.common_name,
      };
    case "batch_carrier_assignment":
      return {
        size: "standard",
        entityTypeLabel: "Placement",
        code: ctx.code,
        secondaryLine: ctx.batch.variety
          ? `${ctx.batch.crop.common_name} · ${ctx.batch.variety.name}`
          : ctx.batch.crop.common_name,
      };
    case "harvested_produce_lot":
      return {
        size: "standard",
        entityTypeLabel: "Harvest Lot",
        code: ctx.code,
        secondaryLine: ctx.batch.variety
          ? `${ctx.batch.crop.common_name} · ${ctx.batch.variety.name}`
          : ctx.batch.crop.common_name,
      };
    case "graded_produce_lot":
      return {
        size: "standard",
        entityTypeLabel: "Graded Lot",
        code: ctx.code,
        secondaryLine: ctx.variety ? `${ctx.crop.common_name} · ${ctx.variety.name}` : ctx.crop.common_name,
      };
    case "finished_goods_lot":
      return {
        size: "standard",
        entityTypeLabel: "Finished Goods Lot",
        code: ctx.code,
        secondaryLine: ctx.variety ? `${ctx.crop.common_name} · ${ctx.variety.name}` : ctx.crop.common_name,
      };
  }
}

function errorMessage(error: unknown): string {
  return error instanceof AppError ? error.message : "Something went wrong. Please try again.";
}

export default function LabelPreviewPage() {
  const { farmId, entityType, entityId } = useParams<{ farmId: string; entityType: string; entityId: string }>();
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
              <LabelCard token={token} {...labelContentFor(scanQuery.data)} />
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
                      window.print();
                    },
                    onError: (error) => setPrintError(errorMessage(error)),
                  },
                );
              }}
              disabled={printMutation.isPending}
            >
              {printMutation.isPending ? "Recording print…" : "Print label"}
            </Button>
            {printError && <p className="text-sm text-danger-700">{printError}</p>}
            {lastPrinted && (
              <p className="text-sm text-wl-text-secondary">
                {lastPrinted.isReprint ? "Reprint recorded." : "Print recorded."}
              </p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
