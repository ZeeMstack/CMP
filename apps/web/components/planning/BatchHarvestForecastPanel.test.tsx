import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { CropBatchRead } from "@/lib/api/client";
import { withQueryClient } from "@/lib/test-utils";

import { BatchHarvestForecastPanel } from "./BatchHarvestForecastPanel";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const KG_UOM = { id: "uom-kg", code: "kg", name: "Kilogram", quantity_kind: "mass" };

const BATCH = { id: "batch-1", code: "B-001" } as CropBatchRead;

function forecastStatus(overrides: Record<string, unknown> = {}) {
  return {
    batch_id: "batch-1",
    batch_code: "B-001",
    crop: { id: "crop-1", code: "ICE", common_name: "Iceberg Lettuce" },
    variety: null,
    current_stage: { id: "stage-1", code: "GROW", name: "Growing", stage_category: "growing" },
    current_forecast: {
      id: "fc-1", tenant_id: "t", farm_id: "farm-1", batch_id: "batch-1",
      revision_number: 1, is_current: true, superseded_at: null, superseded_by_forecast_id: null,
      window_start_date: "2026-10-01", window_end_date: "2026-10-08",
      low_quantity: "800", expected_quantity: "1000", high_quantity: "1200", uom: KG_UOM,
      basis: "grower_estimate", notes: null, revision_reason: null,
      recorded_by_user_id: "u1", effective_time: "2026-09-01T00:00:00Z", recorded_time: "2026-09-01T00:00:00Z",
    },
    actual: {
      total_harvested_weight_kg: "300", first_harvest_date: null, latest_harvest_date: null,
      comparable_to_forecast_uom: true, actual_quantity_in_forecast_uom: "300",
      remaining_forecast_quantity_in_forecast_uom: "700",
    },
    open_crop_issue_count: 2,
    active_location_codes: [],
    ...overrides,
  };
}

function stubFetch(overrides: { status?: unknown; statusCode?: number } = {}) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/harvest-forecast/status")) {
        return jsonResponse(overrides.status ?? forecastStatus(), overrides.statusCode ?? 200);
      }
      if (url.includes("/crop-issues")) return jsonResponse([{ id: "issue-1", status: "open" }]);
      return jsonResponse([]);
    }),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("BatchHarvestForecastPanel", () => {
  it("shows Low/Expected/High as distinct figures, separate from Harvested to date -- forecast is never shown as inventory/actual", async () => {
    stubFetch();
    render(withQueryClient(<BatchHarvestForecastPanel farmId="farm-1" batch={BATCH} />));

    await waitFor(() => expect(screen.getByText("1,000 kg")).toBeInTheDocument());
    expect(screen.getByText("800 kg")).toBeInTheDocument();
    expect(screen.getByText("1,200 kg")).toBeInTheDocument();
    expect(screen.getByText("300 kg")).toBeInTheDocument();
    expect(screen.getByText(/remaining against forecast/i)).toHaveTextContent("700 kg");
  });

  it("shows an open Crop Issue risk marker without changing the forecast Expected quantity", async () => {
    stubFetch();
    render(withQueryClient(<BatchHarvestForecastPanel farmId="farm-1" batch={BATCH} />));

    await waitFor(() => expect(screen.getByText("2 open crop issues")).toBeInTheDocument());
    // The forecast quantity is untouched by the risk signal -- still 1,000 kg.
    expect(screen.getByText("1,000 kg")).toBeInTheDocument();
  });

  it("offers 'Record Forecast' (not a form pre-filled with stale data) when the Batch has no forecast yet", async () => {
    // `/harvest-forecast/status` always returns 200 with `current_forecast:
    // null` for a Batch with no forecast -- it never 404s (unlike the plain
    // current-forecast-only GET).
    stubFetch({ status: forecastStatus({ current_forecast: null, open_crop_issue_count: 0 }) });
    render(withQueryClient(<BatchHarvestForecastPanel farmId="farm-1" batch={BATCH} />));

    await waitFor(() => expect(screen.getByText(/no harvest forecast recorded/i)).toBeInTheDocument());
    expect(screen.getByRole("button", { name: /record forecast/i })).toBeInTheDocument();
  });
});
