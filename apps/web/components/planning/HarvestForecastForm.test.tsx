import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { withQueryClient } from "@/lib/test-utils";

import { HarvestForecastForm } from "./HarvestForecastForm";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const UOMS = [{ id: "uom-kg", code: "kg", name: "Kilogram", quantity_kind: "mass" }];

function stubFetch() {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/uoms")) return jsonResponse(UOMS);
      return jsonResponse([]);
    }),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("HarvestForecastForm", () => {
  it("shows Low/Expected/High as distinct fields and submits a valid window", async () => {
    stubFetch();
    const onSubmit = vi.fn();
    render(
      withQueryClient(
        <HarvestForecastForm isRevision={false} onSubmit={onSubmit} onCancel={vi.fn()} isSubmitting={false} />,
      ),
    );

    await waitFor(() => expect(screen.getByText("kg")).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText(/forecast window start/i), { target: { value: "2026-10-01" } });
    fireEvent.change(screen.getByLabelText(/forecast window end/i), { target: { value: "2026-10-08" } });
    fireEvent.change(screen.getByLabelText(/^low quantity$/i), { target: { value: "800" } });
    fireEvent.change(screen.getByLabelText(/^expected quantity$/i), { target: { value: "1000" } });
    fireEvent.change(screen.getByLabelText(/^high quantity$/i), { target: { value: "1200" } });
    fireEvent.change(screen.getByLabelText(/^unit$/i), { target: { value: "uom-kg" } });
    fireEvent.click(screen.getByRole("button", { name: /record forecast/i }));

    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
    const payload = onSubmit.mock.calls[0][0];
    expect(payload).toMatchObject({
      window_start_date: "2026-10-01",
      window_end_date: "2026-10-08",
      low_quantity: "800",
      expected_quantity: "1000",
      high_quantity: "1200",
      quantity_uom_id: "uom-kg",
    });
    expect(payload.client_command_id).toBeTruthy();
  });

  it("rejects LOW greater than EXPECTED client-side and never calls onSubmit", async () => {
    stubFetch();
    const onSubmit = vi.fn();
    render(
      withQueryClient(
        <HarvestForecastForm isRevision={false} onSubmit={onSubmit} onCancel={vi.fn()} isSubmitting={false} />,
      ),
    );

    await waitFor(() => expect(screen.getByText("kg")).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText(/forecast window start/i), { target: { value: "2026-10-01" } });
    fireEvent.change(screen.getByLabelText(/forecast window end/i), { target: { value: "2026-10-08" } });
    fireEvent.change(screen.getByLabelText(/^low quantity$/i), { target: { value: "1100" } });
    fireEvent.change(screen.getByLabelText(/^expected quantity$/i), { target: { value: "1000" } });
    fireEvent.change(screen.getByLabelText(/^high quantity$/i), { target: { value: "1200" } });
    fireEvent.change(screen.getByLabelText(/^unit$/i), { target: { value: "uom-kg" } });
    fireEvent.click(screen.getByRole("button", { name: /record forecast/i }));

    await waitFor(() => expect(screen.getByText(/low must be less than or equal to expected/i)).toBeInTheDocument());
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("PILOT-PLAN-001B section 7: a revision explicitly states history is preserved, and is labeled 'Revise Forecast' not 'Edit'", async () => {
    stubFetch();
    render(
      withQueryClient(
        <HarvestForecastForm isRevision onSubmit={vi.fn()} onCancel={vi.fn()} isSubmitting={false} />,
      ),
    );

    expect(screen.getByText(/creates a new forecast revision/i)).toBeInTheDocument();
    expect(screen.getByText(/previous forecasts remain in history/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /revise forecast/i })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^edit$/i })).not.toBeInTheDocument();
  });

  it("PILOT-PLAN-001B section 18: an unauthorized user's Record Forecast attempt surfaces the backend's 403 truthfully -- this codebase has no client-side permission hook (see app/farms/[farmId]/crop-issues/[issueId]/page.tsx), so every mutation control relies on the backend refusing it, never a silently-succeeding or silently-hidden control", async () => {
    stubFetch();
    render(
      withQueryClient(
        <HarvestForecastForm
          isRevision={false}
          onSubmit={vi.fn()}
          onCancel={vi.fn()}
          isSubmitting={false}
          serverError="You don't have permission to do this. Contact an administrator if you believe this is a mistake."
        />,
      ),
    );

    expect(screen.getByRole("alert")).toHaveTextContent(/don't have permission/i);
    // The control itself is still visible/enabled -- the backend's refusal is what stops the mutation, not a hidden button.
    expect(screen.getByRole("button", { name: /record forecast/i })).toBeEnabled();
  });
});
