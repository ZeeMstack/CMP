"use client";

import { useState } from "react";

import { Button } from "@/components/ui/Button";
import { ErrorState } from "@/components/ErrorState";
import { LoadingSkeleton } from "@/components/LoadingSkeleton";
import { HarvestForecastForm } from "@/components/planning/HarvestForecastForm";
import { HarvestForecastHistoryList } from "@/components/planning/HarvestForecastHistoryList";
import { RiskSignalBadge } from "@/components/planning/RiskSignalBadge";
import type { CropBatchRead, RecordBatchHarvestForecast } from "@/lib/api/client";
import { AppError } from "@/lib/errors/adapter";
import { formatPlanDate } from "@/lib/format/planDate";
import { formatQuantity } from "@/lib/format/planQuantity";
import { useBatchHarvestForecastStatus, useRecordBatchHarvestForecast } from "@/lib/query/hooks";

const BASIS_LABEL: Record<string, string> = {
  grower_estimate: "Grower estimate",
  planning_assumption: "Planning assumption",
  protocol_guidance: "Protocol guidance",
};

/** PILOT-PLAN-001B section 16: the compact Harvest Forecast panel on the
 * Batch page -- FORECAST QUANTITY is never shown as if it were inventory,
 * and a harvested-to-date figure is never shown as if it were the current
 * forecast (see the frozen distinctions in
 * docs/domain/HARVEST_FORECAST_CAPACITY_MODEL.md). Mirrors
 * `BatchProtocolPanel`'s current-status + inline-form shape. */
export function BatchHarvestForecastPanel({ farmId, batch }: { farmId: string; batch: CropBatchRead }) {
  const statusQuery = useBatchHarvestForecastStatus(farmId, batch.id);
  const recordMutation = useRecordBatchHarvestForecast(farmId, batch.id);
  const [recording, setRecording] = useState(false);

  if (statusQuery.isLoading) return <LoadingSkeleton rows={2} label="Loading harvest forecast" />;
  if (statusQuery.error) return <ErrorState error={statusQuery.error} onRetry={() => statusQuery.refetch()} />;
  const status = statusQuery.data;
  if (!status) return null;

  const forecast = status.current_forecast;
  const actual = status.actual;

  function submit(payload: RecordBatchHarvestForecast) {
    recordMutation.mutate(payload, { onSuccess: () => setRecording(false) });
  }

  if (recording || !forecast) {
    return (
      <div className="flex flex-col gap-3">
        {!forecast && !recording && (
          <div className="rounded-lg border border-dashed border-wl-border bg-wl-surface-raised p-4">
            <p className="text-sm font-medium text-wl-text">No harvest forecast recorded</p>
            <p className="mt-1 text-xs text-wl-text-secondary">
              A forecast is a planning estimate, never inventory -- it will not appear in any stock balance.
            </p>
            <Button variant="primary" className="mt-3" onClick={() => setRecording(true)}>
              Record Forecast
            </Button>
          </div>
        )}
        {recording && (
          <HarvestForecastForm
            currentForecast={forecast}
            isRevision={Boolean(forecast)}
            isSubmitting={recordMutation.isPending}
            serverError={recordMutation.error instanceof AppError ? recordMutation.error.message : null}
            onCancel={() => setRecording(false)}
            onSubmit={submit}
          />
        )}
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4 rounded-lg border border-wl-border bg-wl-surface-raised p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-sm font-medium text-wl-text">
            {formatPlanDate(forecast.window_start_date)} – {formatPlanDate(forecast.window_end_date)}
          </p>
          <p className="mt-0.5 text-xs text-wl-text-secondary">
            {BASIS_LABEL[forecast.basis] ?? forecast.basis} · Last revised{" "}
            {new Date(forecast.recorded_time).toLocaleDateString()}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <RiskSignalBadge farmId={farmId} batchId={batch.id} openCropIssueCount={status.open_crop_issue_count} />
          <Button variant="secondary" onClick={() => setRecording(true)}>
            Revise Forecast
          </Button>
        </div>
      </div>

      <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <div>
          <dt className="text-xs text-wl-text-tertiary">Low</dt>
          <dd className="text-sm font-medium text-wl-text">{formatQuantity(forecast.low_quantity, forecast.uom.code)}</dd>
        </div>
        <div>
          <dt className="text-xs text-wl-text-tertiary">Expected</dt>
          <dd className="text-sm font-medium text-wl-text">
            {formatQuantity(forecast.expected_quantity, forecast.uom.code)}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-wl-text-tertiary">High</dt>
          <dd className="text-sm font-medium text-wl-text">{formatQuantity(forecast.high_quantity, forecast.uom.code)}</dd>
        </div>
        <div>
          <dt className="text-xs text-wl-text-tertiary">Harvested to date</dt>
          <dd className="text-sm font-medium text-wl-text">
            {formatQuantity(String(actual.total_harvested_weight_kg), "kg")}
          </dd>
        </div>
      </dl>

      {actual.comparable_to_forecast_uom ? (
        <p className="text-xs text-wl-text-secondary">
          Remaining against forecast: {formatQuantity(actual.remaining_forecast_quantity_in_forecast_uom ?? "0", forecast.uom.code)}
        </p>
      ) : (
        <p className="text-xs text-wl-text-secondary">
          Not comparable -- harvested weight (kg) has no known conversion to the forecast unit ({forecast.uom.code}).
        </p>
      )}

      <HarvestForecastHistoryList farmId={farmId} batchId={batch.id} />
    </div>
  );
}
