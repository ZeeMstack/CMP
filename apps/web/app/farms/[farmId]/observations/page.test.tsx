import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { withQueryClient } from "@/lib/test-utils";

let searchParams = new URLSearchParams();

vi.mock("next/navigation", () => ({
  useParams: () => ({ farmId: "farm-1" }),
  useSearchParams: () => searchParams,
}));

import ObservationsPage from "./page";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const BATCH = {
  id: "batch-1", code: "LET-001", crop: { id: "crop-1", code: "LET", common_name: "Iceberg" },
  variety: { id: "var-1", code: "MAM", name: "Mamutik" }, state: "active",
  current_stage: { id: "stage-1", code: "PROD", name: "Production", is_terminal: false, stage_category: "production" },
  sowing_origins: [], sown_effective_time: "2026-08-01T00:00:00Z",
  placement: {
    active_carrier_count: 1, placed_carrier_count: 1, unplaced_carrier_count: 0,
    placements: [
      {
        carrier_id: "carrier-1", carrier_code: "PP-001", location_id: "loc-1", location_code: "T04",
        location_name: "Table 04",
        path: [
          { id: "gh-1", code: "GH-01", name: "GH-01" },
          { id: "z-1", code: "Z01", name: "Zone 1" },
          { id: "s-1", code: "S02", name: "Span 2" },
          { id: "t-1", code: "T04", name: "Table 04" },
        ],
      },
    ],
    common_ancestor_path: null,
  },
  open_quality_hold_count: 0,
};

const DEFINITIONS = [
  {
    id: "def-height", tenant_id: "t-1", code: "PLANT-HEIGHT", name: "Plant Height", description: null,
    value_type: "decimal", unit: "cm", target_scope: "crop_batch", min_value: null, max_value: null,
    status: "active", created_by_user_id: "u-1", created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z",
  },
  {
    id: "def-pest", tenant_id: "t-1", code: "PEST-SIGNS", name: "Pest Signs", description: null,
    value_type: "boolean", unit: null, target_scope: "carrier_assignment", min_value: null, max_value: null,
    status: "active", created_by_user_id: "u-1", created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z",
  },
];

const TARGETS = [{ id: "bca-1", carrier: { id: "carrier-1", code: "PP-001", carrier_type: { id: "ct-1", code: "plate", name: "Plate" } }, location_label: "GH-01 / Z01 / S02 / T04" }];

const HISTORY_EVENT = {
  id: "evt-1", tenant_id: "t-1", farm_id: "farm-1", batch_id: "batch-1", batch_code: "LET-001",
  workflow_version_id: "wf-1", stage: { id: "stage-1", code: "PROD", name: "Production", is_terminal: false },
  effective_time: "2026-09-09T09:00:00Z", recorded_time: "2026-09-09T09:00:05Z", actor_user_id: "user-1",
  client_command_id: "cmd-1", note: null,
  values: [
    {
      id: "val-1", definition: { id: "def-height", code: "PLANT-HEIGHT", name: "Plant Height", value_type: "decimal", unit: "cm" },
      carrier: null, batch_carrier_assignment_id: null, value_integer: null, value_decimal: "18.500",
      value_boolean: null, value_text: null, note: null,
    },
  ],
  germination_checks: [],
};

function stubFetch(overrides: Record<string, unknown> = {}) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      if (url.includes("/observation-definitions")) return jsonResponse(overrides.definitions ?? DEFINITIONS);
      if (url.includes("/crop-batches/operational-summary")) return jsonResponse(overrides.batches ?? [BATCH]);
      if (url.includes("/observation-targets")) return jsonResponse(overrides.targets ?? TARGETS);
      if (url.match(/\/crop-batches\/[^/]+\/observations$/) && method === "POST") {
        if (overrides.recordError) {
          return jsonResponse({ detail: "observation definition PEST-SIGNS is not active" }, 422);
        }
        (overrides.postedBodies as unknown[] | undefined)?.push(JSON.parse(String(init?.body)));
        return jsonResponse(overrides.recordResult ?? HISTORY_EVENT, 201);
      }
      if (url.includes("/observations")) return jsonResponse(overrides.history ?? [HISTORY_EVENT]);
      if (url.match(/\/farms\/farm-1$/)) return jsonResponse({ id: "farm-1", timezone: "Asia/Dubai" });
      return jsonResponse([]);
    }),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
  searchParams = new URLSearchParams();
});

describe("ObservationsPage", () => {
  it("shows an empty prompt before a batch is selected, then lists the batch in the selector", async () => {
    stubFetch();
    render(withQueryClient(<ObservationsPage />));
    expect(screen.getByText(/select a batch to view or record observations/i)).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText(/LET-001/)).toBeInTheDocument());
  });

  it("renders existing observation history with operator-friendly values, never raw JSON", async () => {
    stubFetch();
    render(withQueryClient(<ObservationsPage />));
    await waitFor(() => expect(screen.getByText(/LET-001/)).toBeInTheDocument());
    fireEvent.change(screen.getByRole("combobox", { name: /batch/i }), { target: { value: "batch-1" } });

    await waitFor(() => expect(screen.getByText(/18.5 cm/)).toBeInTheDocument());
    expect(screen.queryByText(/value_decimal/)).not.toBeInTheDocument();
    expect(screen.queryByText("18.500")).not.toBeInTheDocument();
  });

  it("opens a compact Record observation form, rendering each definition's own input type", async () => {
    stubFetch();
    render(withQueryClient(<ObservationsPage />));
    await waitFor(() => expect(screen.getByText(/LET-001/)).toBeInTheDocument());
    fireEvent.change(screen.getByRole("combobox", { name: /batch/i }), { target: { value: "batch-1" } });
    await waitFor(() => expect(screen.getByText(/18.5 cm/)).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: /\+ record observation/i }));
    await waitFor(() => expect(screen.getByText(/record observation — let-001/i)).toBeInTheDocument());

    // decimal definition -> a number input
    expect(screen.getByRole("spinbutton", { name: /plant height/i })).toBeInTheDocument();
    // boolean definition -> a Yes/No select, plus a required target select
    expect(screen.getByRole("combobox", { name: /^pest signs$/i })).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: /target \(required\)/i })).toBeInTheDocument();
  });

  it("requires a target for a carrier_assignment-scoped definition before submit", async () => {
    stubFetch();
    render(withQueryClient(<ObservationsPage />));
    await waitFor(() => expect(screen.getByText(/LET-001/)).toBeInTheDocument());
    fireEvent.change(screen.getByRole("combobox", { name: /batch/i }), { target: { value: "batch-1" } });
    await waitFor(() => expect(screen.getByText(/18.5 cm/)).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /\+ record observation/i }));
    await waitFor(() => expect(screen.getByRole("combobox", { name: /^pest signs$/i })).toBeInTheDocument());

    fireEvent.change(screen.getByRole("combobox", { name: /^pest signs$/i }), { target: { value: "true" } });
    fireEvent.click(screen.getByRole("button", { name: /^record 1 observation$/i }));

    await waitFor(() => expect(screen.getByText(/requires a target/i)).toBeInTheDocument());
  });

  it("submits the correct ObservationEventCreate payload and refreshes history on success", async () => {
    const postedBodies: unknown[] = [];
    stubFetch({ postedBodies });
    render(withQueryClient(<ObservationsPage />));
    await waitFor(() => expect(screen.getByText(/LET-001/)).toBeInTheDocument());
    fireEvent.change(screen.getByRole("combobox", { name: /batch/i }), { target: { value: "batch-1" } });
    await waitFor(() => expect(screen.getByText(/18.5 cm/)).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /\+ record observation/i }));
    await waitFor(() => expect(screen.getByRole("spinbutton", { name: /plant height/i })).toBeInTheDocument());

    fireEvent.change(screen.getByRole("spinbutton", { name: /plant height/i }), { target: { value: "21.5" } });
    fireEvent.click(screen.getByRole("button", { name: /^record 1 observation$/i }));

    await waitFor(() => expect(screen.getByText(/recorded 1 observation/i)).toBeInTheDocument());
    expect(postedBodies).toHaveLength(1);
    const body = postedBodies[0] as { values: Array<Record<string, unknown>> };
    expect(body.values).toEqual([
      { observation_definition_id: "def-height", batch_carrier_assignment_id: null, value_decimal: "21.5" },
    ]);
  });

  it("shows a clear backend validation error and preserves the entered value", async () => {
    stubFetch({ recordError: true });
    render(withQueryClient(<ObservationsPage />));
    await waitFor(() => expect(screen.getByText(/LET-001/)).toBeInTheDocument());
    fireEvent.change(screen.getByRole("combobox", { name: /batch/i }), { target: { value: "batch-1" } });
    await waitFor(() => expect(screen.getByText(/18.5 cm/)).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /\+ record observation/i }));
    await waitFor(() => expect(screen.getByRole("spinbutton", { name: /plant height/i })).toBeInTheDocument());

    fireEvent.change(screen.getByRole("spinbutton", { name: /plant height/i }), { target: { value: "21.5" } });
    fireEvent.click(screen.getByRole("button", { name: /^record 1 observation$/i }));

    await waitFor(() => expect(screen.getByText(/not active/i)).toBeInTheDocument());
    expect(screen.getByRole("spinbutton", { name: /plant height/i })).toHaveValue(21.5);
  });

  it("never renders a raw UUID or raw enum literal in the batch selector or history", async () => {
    stubFetch();
    render(withQueryClient(<ObservationsPage />));
    await waitFor(() => expect(screen.getByText(/LET-001/)).toBeInTheDocument());
    const options = within(screen.getByRole("combobox", { name: /batch/i })).getAllByRole("option");
    for (const option of options) {
      expect(option.textContent ?? "").not.toMatch(/[0-9a-f]{8}-[0-9a-f]{4}-/i);
    }
    fireEvent.change(screen.getByRole("combobox", { name: /batch/i }), { target: { value: "batch-1" } });
    await waitFor(() => expect(screen.getByText(/18.5 cm/)).toBeInTheDocument());
    expect(screen.queryByText("TRUE")).not.toBeInTheDocument();
  });

  it("prefills the batch and opens the form directly when navigated from a production-page shortcut", async () => {
    searchParams = new URLSearchParams("batchId=batch-1");
    stubFetch();
    render(withQueryClient(<ObservationsPage />));
    await waitFor(() => expect(screen.getByText(/record observation — let-001/i)).toBeInTheDocument());
  });
});
