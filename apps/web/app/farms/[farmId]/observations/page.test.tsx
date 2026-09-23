import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AuthBootstrapProvider } from "@/lib/auth/AuthBootstrapProvider";
import { queryKeys } from "@/lib/query/keys";
import { DEFAULT_TEST_BOOTSTRAP, TEST_TENANT_ID, withQueryClient } from "@/lib/test-utils";

let searchParams = new URLSearchParams();

vi.mock("next/navigation", () => ({
  useParams: () => ({ farmId: "farm-1" }),
  useSearchParams: () => searchParams,
}));

import ObservationsPage from "./page";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

/** Like `withQueryClient`, but also hands back the `QueryClient` so a test
 * can directly manipulate/refetch cache entries (e.g. simulate a background
 * target refresh landing after the operator has already made a manual
 * choice) without a second network round trip. */
function renderWithClient(children: ReactNode) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  queryClient.setQueryData(queryKeys.authBootstrap(), DEFAULT_TEST_BOOTSTRAP);
  const utils = render(
    <QueryClientProvider client={queryClient}>
      <AuthBootstrapProvider>{children}</AuthBootstrapProvider>
    </QueryClientProvider>,
  );
  return { ...utils, queryClient };
}

/** A promise this test controls the resolution of -- used to force the
 * `/observation-definitions` fetch to stay pending while other queries
 * (targets, batches, history) resolve normally, reproducing the exact race
 * PILOT-BLOCKER-011 fixes: targets ready before definitions. */
function deferredResponse() {
  let resolve!: (body: unknown) => void;
  const promise = new Promise<Response>((res) => {
    resolve = (body: unknown) => res(jsonResponse(body));
  });
  return { promise, resolve };
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
const TARGET_B = { id: "bca-2", carrier: { id: "carrier-2", code: "PP-002", carrier_type: { id: "ct-1", code: "plate", name: "Plate" } }, location_label: "GH-01 / Z01 / S02 / T05" };

function manyTargetableDefinitions(count: number) {
  return Array.from({ length: count }, (_, i) => ({
    id: `def-${i}`, tenant_id: "t-1", code: `MEASURE-${i}`, name: `Measure ${i}`, description: null,
    value_type: "decimal", unit: "cm", target_scope: "either", min_value: null, max_value: null,
    status: "active", created_by_user_id: "u-1", created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z",
  }));
}

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

  it("PILOT-UX-003: confirms before discarding an in-progress draft when the operator switches Batch", async () => {
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(false);
    stubFetch({ batches: [BATCH, { ...BATCH, id: "batch-2", code: "LET-002" }] });
    render(withQueryClient(<ObservationsPage />));
    await waitFor(() => expect(screen.getByText(/LET-001/)).toBeInTheDocument());
    fireEvent.change(screen.getByRole("combobox", { name: /batch/i }), { target: { value: "batch-1" } });
    await waitFor(() => expect(screen.getByRole("button", { name: /\+ record observation/i })).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /\+ record observation/i }));
    await waitFor(() => expect(screen.getByRole("spinbutton", { name: /plant height/i })).toBeInTheDocument());
    fireEvent.change(screen.getByRole("spinbutton", { name: /plant height/i }), { target: { value: "21.5" } });

    fireEvent.change(screen.getByRole("combobox", { name: /batch/i }), { target: { value: "batch-2" } });
    expect(confirmSpy).toHaveBeenCalled();
    // Declined the confirm -- the draft (and its Batch) must still be there.
    expect(screen.getByRole("spinbutton", { name: /plant height/i })).toHaveValue(21.5);
    expect(screen.getByText(/record observation — let-001/i)).toBeInTheDocument();
    confirmSpy.mockRestore();
  });

  it("PILOT-UX-003: switches Batch without confirming when the form is untouched", async () => {
    const confirmSpy = vi.spyOn(window, "confirm");
    stubFetch({ batches: [BATCH, { ...BATCH, id: "batch-2", code: "LET-002" }] });
    render(withQueryClient(<ObservationsPage />));
    await waitFor(() => expect(screen.getByText(/LET-001/)).toBeInTheDocument());
    fireEvent.change(screen.getByRole("combobox", { name: /batch/i }), { target: { value: "batch-1" } });
    await waitFor(() => expect(screen.getByRole("button", { name: /\+ record observation/i })).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /\+ record observation/i }));
    await waitFor(() => expect(screen.getByRole("spinbutton", { name: /plant height/i })).toBeInTheDocument());

    fireEvent.change(screen.getByRole("combobox", { name: /batch/i }), { target: { value: "batch-2" } });
    expect(confirmSpy).not.toHaveBeenCalled();
    confirmSpy.mockRestore();
  });

  // --- PILOT-BLOCKER-011 (Astra R5: carried Observation target initialization) ---

  it("R5.1/2/5/7: targets resolve before definitions -- the carried assignment is still applied to a compatible (assignment-only) measurement once both are ready, and submission matches what was shown", async () => {
    searchParams = new URLSearchParams("batchId=batch-1&assignmentId=bca-1");
    const definitionsDeferred = deferredResponse();
    const postedBodies: unknown[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        const method = init?.method ?? "GET";
        if (url.includes("/observation-definitions")) return definitionsDeferred.promise;
        if (url.includes("/crop-batches/operational-summary")) return jsonResponse([BATCH]);
        if (url.includes("/observation-targets")) return jsonResponse(TARGETS);
        if (url.match(/\/crop-batches\/[^/]+\/observations$/) && method === "POST") {
          postedBodies.push(JSON.parse(String(init?.body)));
          return jsonResponse(HISTORY_EVENT, 201);
        }
        if (url.includes("/observations")) return jsonResponse([]);
        if (url.match(/\/farms\/farm-1$/)) return jsonResponse({ id: "farm-1", timezone: "Asia/Dubai" });
        return jsonResponse([]);
      }),
    );

    render(withQueryClient(<ObservationsPage />));

    // The form opens immediately (batchId prefilled); targets/batches
    // resolve, but definitions are still in flight -- the exact race.
    await waitFor(() => expect(screen.getByText(/record observation — let-001/i)).toBeInTheDocument());
    await waitFor(() => expect(screen.getByText(/loading observation definitions/i)).toBeInTheDocument());
    // An in-flight read must never render as a confirmed "nothing configured".
    expect(screen.queryByText(/no active observation definitions/i)).not.toBeInTheDocument();

    definitionsDeferred.resolve(DEFINITIONS);

    // Once both are ready, the Primary target selector shows the carried
    // assignment.
    await waitFor(() => expect(screen.getByRole("combobox", { name: /primary target/i })).toHaveValue("bca-1"));
    // The actual defect: the compatible (carrier_assignment-scoped)
    // measurement's own row target must ALSO be initialized -- a correct
    // Primary selector alone was never enough.
    expect(screen.getByRole("combobox", { name: /target \(required\)/i })).toHaveValue("bca-1");
    // The inline "Review" summary already reflects the same effective target.
    expect(screen.getByText(/applies to: pp-001/i)).toBeInTheDocument();

    fireEvent.change(screen.getByRole("combobox", { name: /^pest signs$/i }), { target: { value: "true" } });
    fireEvent.click(screen.getByRole("button", { name: /^record 1 observation$/i }));

    // No false "requires a target" validation error.
    expect(screen.queryByText(/requires a target/i)).not.toBeInTheDocument();
    await waitFor(() => expect(postedBodies).toHaveLength(1));
    const body = postedBodies[0] as { values: Array<Record<string, unknown>> };
    expect(body.values).toEqual([
      { observation_definition_id: "def-pest", batch_carrier_assignment_id: "bca-1", value_boolean: true },
    ]);
  });

  it("R5.4: an invalid/stale initial target does not silently select a different target", async () => {
    searchParams = new URLSearchParams("batchId=batch-1&assignmentId=does-not-exist");
    stubFetch();
    render(withQueryClient(<ObservationsPage />));
    await waitFor(() => expect(screen.getByText(/record observation — let-001/i)).toBeInTheDocument());
    await waitFor(() => expect(screen.getByRole("combobox", { name: /primary target/i })).toBeInTheDocument());
    expect(screen.getByRole("combobox", { name: /primary target/i })).toHaveValue("");
    expect(screen.getByRole("combobox", { name: /target \(required\)/i })).toHaveValue("");
  });

  it("R5.3: a manual per-row target override survives a later targets refetch -- never overwritten by default initialization", async () => {
    searchParams = new URLSearchParams("batchId=batch-1&assignmentId=bca-1");
    stubFetch({ targets: [TARGETS[0], TARGET_B] });
    const { queryClient } = renderWithClient(<ObservationsPage />);
    await waitFor(() => expect(screen.getByRole("combobox", { name: /primary target/i })).toHaveValue("bca-1"));
    expect(screen.getByRole("combobox", { name: /target \(required\)/i })).toHaveValue("bca-1");

    // The operator deliberately overrides just this one measurement's target.
    fireEvent.change(screen.getByRole("combobox", { name: /target \(required\)/i }), { target: { value: "bca-2" } });
    expect(screen.getByRole("combobox", { name: /target \(required\)/i })).toHaveValue("bca-2");

    // A later background refetch of the targets query must not reset it.
    await queryClient.refetchQueries({ queryKey: queryKeys.observationTargets(TEST_TENANT_ID, "farm-1", "batch-1") });
    await waitFor(() => expect(screen.getByRole("combobox", { name: /target \(required\)/i })).toHaveValue("bca-2"));
    expect(screen.getByRole("combobox", { name: /primary target/i })).toHaveValue("bca-1");
  });

  it("R5.6: choosing a Primary target does not reveal optional measurements beyond the routine limit", async () => {
    stubFetch({ definitions: manyTargetableDefinitions(8) });
    render(withQueryClient(<ObservationsPage />));
    await waitFor(() => expect(screen.getByText(/LET-001/)).toBeInTheDocument());
    fireEvent.change(screen.getByRole("combobox", { name: /batch/i }), { target: { value: "batch-1" } });
    await waitFor(() => expect(screen.getByRole("button", { name: /\+ record observation/i })).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /\+ record observation/i }));

    await waitFor(() => expect(screen.getByRole("combobox", { name: /primary target/i })).toBeInTheDocument());
    expect(screen.getByRole("button", { name: /show 2 more measurement/i })).toBeInTheDocument();
    expect(screen.getAllByRole("spinbutton")).toHaveLength(6);

    fireEvent.change(screen.getByRole("combobox", { name: /primary target/i }), { target: { value: "bca-1" } });

    // Still only the routine 6 -- picking a target never silently expands
    // the optional-measurement list.
    expect(screen.getByRole("button", { name: /show 2 more measurement/i })).toBeInTheDocument();
    expect(screen.getAllByRole("spinbutton")).toHaveLength(6);
  });
});

describe("ObservationsPage frozen command + exact target (UX-OPS-001C/R1)", () => {
  function stubSequenced(statuses: number[]) {
    const bodies: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        const method = init?.method ?? "GET";
        if (url.includes("/observation-definitions")) return jsonResponse(DEFINITIONS);
        if (url.includes("/crop-batches/operational-summary")) return jsonResponse([BATCH]);
        if (url.includes("/observation-targets")) return jsonResponse(TARGETS);
        if (url.match(/\/crop-batches\/[^/]+\/observations$/) && method === "POST") {
          bodies.push(String(init?.body));
          const status = statuses.shift() ?? 201;
          return status >= 400 ? jsonResponse({ detail: "failure" }, status) : jsonResponse(HISTORY_EVENT, 201);
        }
        if (url.includes("/observations")) return jsonResponse([HISTORY_EVENT]);
        if (url.match(/\/farms\/farm-1$/)) return jsonResponse({ id: "farm-1", timezone: "Asia/Dubai" });
        return jsonResponse([]);
      }),
    );
    return bodies;
  }

  async function openFormAndFill() {
    await waitFor(() => expect(screen.getByText(/LET-001/)).toBeInTheDocument());
    fireEvent.change(screen.getByRole("combobox", { name: /batch/i }), { target: { value: "batch-1" } });
    await waitFor(() => expect(screen.getByText(/18.5 cm/)).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /\+ record observation/i }));
    await waitFor(() => expect(screen.getByRole("spinbutton", { name: /plant height/i })).toBeInTheDocument());
    fireEvent.change(screen.getByRole("spinbutton", { name: /plant height/i }), { target: { value: "21.5" } });
  }

  it("uncertain: fields, Cancel, and the Batch selector lock; Retry resends the byte-identical payload", async () => {
    const bodies = stubSequenced([503, 201]);
    render(withQueryClient(<ObservationsPage />));
    await openFormAndFill();
    fireEvent.click(screen.getByRole("button", { name: /^record 1 observation$/i }));

    await waitFor(() => expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument());
    expect(screen.getByRole("spinbutton", { name: /plant height/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Cancel" })).toBeDisabled();
    expect(screen.getByRole("combobox", { name: /batch/i })).toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(screen.getByText(/recorded 1 observation/i)).toBeInTheDocument());
    expect(bodies).toHaveLength(2);
    expect(bodies[1]).toBe(bodies[0]);
  });

  it("definitive rejection unlocks editing and the edited resubmission gets a new client_command_id", async () => {
    const bodies = stubSequenced([422, 201]);
    render(withQueryClient(<ObservationsPage />));
    await openFormAndFill();
    fireEvent.click(screen.getByRole("button", { name: /^record 1 observation$/i }));
    await waitFor(() => expect(screen.getByRole("spinbutton", { name: /plant height/i })).not.toBeDisabled());
    fireEvent.change(screen.getByRole("spinbutton", { name: /plant height/i }), { target: { value: "22" } });
    fireEvent.click(screen.getByRole("button", { name: /^record 1 observation$/i }));
    await waitFor(() => expect(bodies).toHaveLength(2));
    expect(JSON.parse(bodies[1]).client_command_id).not.toBe(JSON.parse(bodies[0]).client_command_id);
  });

  it("shows the carried placement's carrier and location, and hands exactly it to Inspect Crop", async () => {
    searchParams = new URLSearchParams("batchId=batch-1&assignmentId=bca-1");
    stubFetch();
    render(withQueryClient(<ObservationsPage />));
    await waitFor(() =>
      expect(screen.getByText("Exact placement · Derived").nextElementSibling).toHaveTextContent("PP-001 — GH-01 / Z01 / S02 / T04"),
    );
    expect(screen.getByRole("link", { name: /inspect crop — PP-001/i })).toHaveAttribute(
      "href",
      "/farms/farm-1/production/inspect?batchId=batch-1&assignmentId=bca-1",
    );
  });

  it("a carried placement that is no longer an active target is flagged and never passed on", async () => {
    searchParams = new URLSearchParams("batchId=batch-1&assignmentId=bca-gone");
    stubFetch();
    render(withQueryClient(<ObservationsPage />));
    await waitFor(() => expect(screen.getByText(/no longer an active placement of this batch/i)).toBeInTheDocument());
    expect(screen.getByRole("link", { name: /inspect crop \(choose placement\)/i })).toHaveAttribute(
      "href",
      "/farms/farm-1/production/inspect?batchId=batch-1",
    );
  });
});
