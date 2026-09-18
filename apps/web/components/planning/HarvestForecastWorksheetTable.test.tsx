import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { withQueryClient } from "@/lib/test-utils";

import { HarvestForecastWorksheetTable } from "./HarvestForecastWorksheetTable";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("HarvestForecastWorksheetTable", () => {
  it("PILOT-PLAN-001B section 19: a forecast-summary API failure shows the error state, never 'No forecasts' (LOADING/ERROR != EMPTY)", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes("/harvest-forecast-summary")) return jsonResponse({ detail: "Server error" }, 500);
        return jsonResponse([]);
      }),
    );
    render(withQueryClient(<HarvestForecastWorksheetTable farmId="farm-1" periodStart="2026-10-01" periodEnd="2026-11-01" />));

    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
    expect(screen.queryByText(/no batches match/i)).not.toBeInTheDocument();
  });
});
