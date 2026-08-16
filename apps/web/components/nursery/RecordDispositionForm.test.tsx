import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { withQueryClient } from "@/lib/test-utils";

import { RecordDispositionForm } from "./RecordDispositionForm";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const TRAYS = [
  {
    batch_id: "batch-1", batch_code: "CB-0001", tray_id: "tray-1", tray_code: "ST-0001",
    crop_common_name: "Iceberg", variety_name: "Mamutik", seed_lot_code: "LOT-01",
    batch_carrier_assignment_id: "bca-1", seedling_entry_id: "se-1",
    starting_living_seedling_count: 196, total_reduction_magnitude: 0, total_reversal_magnitude: 0,
    current_living_seedling_count: 196, is_depleted: false, event_count: 0,
    seedling_table_id: "table-1", seedling_table_code: "ST01",
    assignment_active: true, assignment_released_effective_time: null,
  },
  {
    batch_id: "batch-2", batch_code: "CB-0002", tray_id: "tray-2", tray_code: "ST-0002",
    crop_common_name: "Iceberg", variety_name: "Mamutik", seed_lot_code: "LOT-01",
    batch_carrier_assignment_id: "bca-2", seedling_entry_id: "se-2",
    starting_living_seedling_count: 190, total_reduction_magnitude: 190, total_reversal_magnitude: 0,
    current_living_seedling_count: 0, is_depleted: true, event_count: 3,
    seedling_table_id: "table-2", seedling_table_code: "ST02",
    assignment_active: true, assignment_released_effective_time: null,
  },
  {
    batch_id: "batch-3", batch_code: "CB-0003", tray_id: "tray-3", tray_code: "ST-0003",
    crop_common_name: "Iceberg", variety_name: "Mamutik", seed_lot_code: "LOT-01",
    batch_carrier_assignment_id: "bca-3", seedling_entry_id: "se-3",
    starting_living_seedling_count: 180, total_reduction_magnitude: 0, total_reversal_magnitude: 0,
    current_living_seedling_count: 180, is_depleted: false, event_count: 0,
    seedling_table_id: "table-3", seedling_table_code: "ST03",
    assignment_active: false, assignment_released_effective_time: "2026-08-02T00:00:00Z",
  },
];

const REASONS = [
  { code: "WEAK_SEEDLING", name: "Weak seedling" },
  { code: "DISEASE", name: "Disease" },
  { code: "OTHER", name: "Other" },
];

function stubFetch(overrides: Record<string, unknown> = {}) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/nursery/seedling/biological-trays")) return jsonResponse(overrides.trays ?? TRAYS);
      if (url.includes("/nursery/seedling/disposition-reasons")) return jsonResponse(overrides.reasons ?? REASONS);
      return jsonResponse([]);
    }),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

async function configureRecord() {
  await waitFor(() => expect(screen.getByText(/CB-0001 — ST-0001/)).toBeInTheDocument());
  fireEvent.change(screen.getByLabelText(/seed tray/i), { target: { value: "bca-1" } });
  fireEvent.change(screen.getByLabelText(/quantity/i), { target: { value: "4" } });
  fireEvent.change(screen.getByLabelText(/reason/i), { target: { value: "WEAK_SEEDLING" } });
  fireEvent.change(screen.getByLabelText(/^date$/i), { target: { value: "2026-08-10" } });
  fireEvent.change(screen.getByLabelText(/^time$/i), { target: { value: "09:00" } });
}

describe("RecordDispositionForm", () => {
  it("lists only Trays with an active assignment and a non-zero current balance", async () => {
    stubFetch();
    render(withQueryClient(<RecordDispositionForm farmId="farm-1" onSubmit={vi.fn()} onCancel={vi.fn()} isSubmitting={false} />));
    await waitFor(() => expect(screen.getByText(/CB-0001 — ST-0001/)).toBeInTheDocument());
    expect(screen.queryByText(/CB-0002 — ST-0002/)).not.toBeInTheDocument();
    expect(screen.queryByText(/CB-0003 — ST-0003/)).not.toBeInTheDocument();
  });

  it("requires a note when reason is Other", async () => {
    stubFetch();
    render(withQueryClient(<RecordDispositionForm farmId="farm-1" onSubmit={vi.fn()} onCancel={vi.fn()} isSubmitting={false} />));
    await configureRecord();
    fireEvent.change(screen.getByLabelText(/reason/i), { target: { value: "OTHER" } });
    fireEvent.click(screen.getByRole("button", { name: "Review" }));
    await waitFor(() => expect(screen.getByText(/note is required when reason is other/i)).toBeInTheDocument());
  });

  it("shows a review with no raw UUIDs, then submits a positive-quantity payload with no client-computed balance", async () => {
    stubFetch();
    const onSubmit = vi.fn();
    render(withQueryClient(<RecordDispositionForm farmId="farm-1" onSubmit={onSubmit} onCancel={vi.fn()} isSubmitting={false} />));
    await configureRecord();
    fireEvent.click(screen.getByRole("button", { name: "Review" }));

    await waitFor(() => expect(screen.getByText("Review before recording")).toBeInTheDocument());
    expect(screen.getByText("CB-0001")).toBeInTheDocument();
    expect(screen.getByText("ST-0001")).toBeInTheDocument();
    expect(screen.getByText("Weak seedling")).toBeInTheDocument();
    expect(screen.queryByText(/bca-1|tray-1|se-1/)).not.toBeInTheDocument();
    expect(onSubmit).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Record disposition" }));
    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
    const payload = onSubmit.mock.calls[0][0];
    expect(payload.batch_carrier_assignment_id).toBe("bca-1");
    expect(payload.quantity).toBe(4);
    expect(payload.reason_code).toBe("WEAK_SEEDLING");
    expect(payload).not.toHaveProperty("current_living_seedling_count");
    expect(payload).not.toHaveProperty("starting_living_seedling_count");
    expect(payload).not.toHaveProperty("resulting_living_seedling_count");
  });

  it("shows a server error (e.g. assignment released)", async () => {
    stubFetch();
    render(
      withQueryClient(
        <RecordDispositionForm
          farmId="farm-1" onSubmit={vi.fn()} onCancel={vi.fn()} isSubmitting={false}
          serverError="This Tray's assignment has already been released."
        />,
      ),
    );
    await configureRecord();
    fireEvent.click(screen.getByRole("button", { name: "Review" }));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(/already been released/i));
  });

  it("calls onCancel without submitting", async () => {
    stubFetch();
    const onSubmit = vi.fn();
    const onCancel = vi.fn();
    render(withQueryClient(<RecordDispositionForm farmId="farm-1" onSubmit={onSubmit} onCancel={onCancel} isSubmitting={false} />));
    await waitFor(() => expect(screen.getByText(/CB-0001 — ST-0001/)).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onCancel).toHaveBeenCalledTimes(1);
    expect(onSubmit).not.toHaveBeenCalled();
  });
});
