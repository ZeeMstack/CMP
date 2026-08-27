import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { withQueryClient } from "@/lib/test-utils";

import PackingPage from "./page";

vi.mock("next/navigation", () => ({
  useParams: () => ({ farmId: "farm-1" }),
}));

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const CROP_LETTUCE = { id: "crop-1", code: "LET", common_name: "Lettuce" };
const CROP_TOMATO = { id: "crop-2", code: "TOM", common_name: "Tomato" };

const GPL_1 = {
  id: "gpl-1", tenant_id: "t", farm_id: "farm-1", grading_event_id: "ge-1", code: "GA-001",
  crop: CROP_LETTUCE, variety: null, grade_definition_version_id: "gdv-1",
  original_received_weight_kg: "60.000", original_received_whole_unit_count: null,
  effective_time: "2026-01-10T08:00:00Z", recorded_at: "2026-01-10T08:05:00Z",
};
const GPL_2 = {
  id: "gpl-2", tenant_id: "t", farm_id: "farm-1", grading_event_id: "ge-1", code: "GA-002",
  crop: CROP_LETTUCE, variety: null, grade_definition_version_id: "gdv-1",
  original_received_weight_kg: "40.000", original_received_whole_unit_count: null,
  effective_time: "2026-01-10T08:00:00Z", recorded_at: "2026-01-10T08:05:00Z",
};
const GPL_OTHER_CROP = {
  id: "gpl-3", tenant_id: "t", farm_id: "farm-1", grading_event_id: "ge-2", code: "TM-001",
  crop: CROP_TOMATO, variety: null, grade_definition_version_id: "gdv-t1",
  original_received_weight_kg: "30.000", original_received_whole_unit_count: null,
  effective_time: "2026-01-10T08:00:00Z", recorded_at: "2026-01-10T08:05:00Z",
};

function balanceFor(lot: {
  id: string; code: string; original_received_weight_kg: string; original_received_whole_unit_count: number | null;
  effective_time: string;
}) {
  return {
    graded_produce_lot_id: lot.id, graded_produce_lot_code: lot.code,
    received_weight_kg: lot.original_received_weight_kg, available_weight_kg: lot.original_received_weight_kg,
    received_whole_unit_count: lot.original_received_whole_unit_count,
    available_whole_unit_count: lot.original_received_whole_unit_count,
    entry_count: 1, last_effective_time: lot.effective_time,
  };
}

// Pack Specification "Retail Pack" (crop-1/Lettuce) with a RETIRED version
// whose historical window (Jan-Jul 2025) is fully before the currently
// ACTIVE version's own window (Jul 2025 onward), plus a DRAFT version that
// must never be selectable at any effective_time. `nominal_net_weight_kg`
// is deliberately far from any weight actually used in the tests below, to
// prove it's never used as an input to the packed-output arithmetic.
const PACK_SPECIFICATIONS_LETTUCE = [
  { id: "ps-1", tenant_id: "t", crop_id: "crop-1", variety_id: null, code: "PS1", name: "Retail Pack", customer_reference: null, created_at: "2025-01-01T00:00:00Z" },
];
const PACK_VERSIONS_PS1 = [
  {
    id: "psv-1", tenant_id: "t", pack_specification_id: "ps-1", version_number: 1, status: "retired",
    grade_definition_version_id: null, packaging_unit_id: "pu-1", nominal_net_weight_kg: "5.000",
    whole_units_per_pack: null, spec_notes: "old pack spec",
    effective_from: "2025-01-01T00:00:00Z", effective_until: "2025-07-01T00:00:00Z",
    created_by: null, created_at: "2025-01-01T00:00:00Z",
  },
  {
    id: "psv-2", tenant_id: "t", pack_specification_id: "ps-1", version_number: 2, status: "active",
    grade_definition_version_id: null, packaging_unit_id: "pu-1", nominal_net_weight_kg: "999.000",
    whole_units_per_pack: null, spec_notes: "current pack spec",
    effective_from: "2025-07-01T00:00:00Z", effective_until: null,
    created_by: null, created_at: "2025-07-01T00:00:00Z",
  },
  {
    id: "psv-3", tenant_id: "t", pack_specification_id: "ps-1", version_number: 3, status: "draft",
    grade_definition_version_id: null, packaging_unit_id: "pu-1", nominal_net_weight_kg: "20.000",
    whole_units_per_pack: null, spec_notes: "upcoming pack spec",
    effective_from: null, effective_until: null, created_by: null, created_at: "2026-01-01T00:00:00Z",
  },
];

function packingEventResult(overrides: Record<string, unknown> = {}) {
  return {
    id: "pe-1", tenant_id: "t", farm_id: "farm-1", pack_specification_version_id: "psv-2",
    grade_definition_version_id: null, crop: CROP_LETTUCE, variety: null,
    finished_goods_lot: { id: "fg-1", code: "FG-001", net_packed_weight_kg: "100.000", package_count: 10 },
    input_lines: [
      { id: "il-1", graded_produce_lot_id: "gpl-1", graded_produce_lot_code: "GA-001", grade_definition_version_id: "gdv-1", consumed_weight_kg: "60.000", consumed_whole_unit_count: null, ledger_entry_id: "le-1", note: null, recorded_time: "2026-08-20T10:00:00Z" },
      { id: "il-2", graded_produce_lot_id: "gpl-2", graded_produce_lot_code: "GA-002", grade_definition_version_id: "gdv-1", consumed_weight_kg: "40.000", consumed_whole_unit_count: null, ledger_entry_id: "le-2", note: null, recorded_time: "2026-08-20T10:00:00Z" },
    ],
    total_input_weight_kg: "100.000", packed_output_weight_kg: "100.000", process_loss_weight_kg: "0", rejected_weight_kg: "0",
    effective_time: "2026-08-20T10:00:00Z", recorded_time: "2026-08-20T10:00:00Z", actor_user_id: "user-1",
    client_command_id: "cmd-1", note: null,
    ...overrides,
  };
}

function stubFetch(overrides: Record<string, unknown> = {}) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? "GET";

      if (url.includes("/packing-events") && method === "POST") {
        if (overrides.recordError) return jsonResponse({ detail: "conflict" }, 409);
        return jsonResponse(overrides.recordResult ?? packingEventResult());
      }
      if (url.includes("/packing-events")) {
        return jsonResponse(overrides.events ?? []);
      }
      if (url.includes("/graded-produce-lots/") && url.includes("/balance")) {
        const lotId = url.match(/graded-produce-lots\/([^/?]+)/)?.[1];
        const lot = [GPL_1, GPL_2, GPL_OTHER_CROP].find((l) => l.id === lotId) ?? GPL_1;
        return jsonResponse(balanceFor(lot));
      }
      if (url.includes("/graded-produce-lots")) {
        return jsonResponse(overrides.lots ?? [GPL_1, GPL_2, GPL_OTHER_CROP]);
      }
      if (url.includes("/recall-cases")) {
        return jsonResponse([]);
      }
      if (url.includes("/pack-specifications/ps-1/versions")) {
        return jsonResponse(PACK_VERSIONS_PS1);
      }
      if (url.includes("/pack-specifications") && url.includes("crop_id=crop-1")) {
        return jsonResponse(PACK_SPECIFICATIONS_LETTUCE);
      }
      return jsonResponse([]);
    }),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

async function addGplToPacking(code: string) {
  await waitFor(() => expect(screen.getByText(code)).toBeInTheDocument());
  const row = screen.getByText(code).closest("li") as HTMLElement;
  await waitFor(() => expect(within(row).getByRole("button", { name: /add to packing/i })).toBeEnabled());
  fireEvent.click(within(row).getByRole("button", { name: /add to packing/i }));
  // `PackingForm` is remounted (via `key={selectedIds.join(",")}`) whenever
  // the selected set changes -- wait for that settled form before the
  // caller interacts with it, or a query against the about-to-be-replaced
  // instance can race the remount.
  await waitFor(() => expect(screen.getByText(new RegExp(`Pack .*${code}`))).toBeInTheDocument());
}

/** Waits for the Pack Specification option to actually exist before
 * selecting it -- `usePackSpecifications` fetches asynchronously, so firing
 * `change` before the option exists has the browser silently ignore the
 * requested value, leaving the field un-selected despite the event having
 * "succeeded" (see the identical note in the Grading page test). */
async function selectPackSpecification(packSpecificationId: string) {
  await waitFor(() => expect(within(screen.getByLabelText(/^pack specification$/i)).getByRole("option", { name: /^Retail Pack/ })).toBeInTheDocument());
  fireEvent.change(screen.getByLabelText(/^pack specification$/i), { target: { value: packSpecificationId } });
}

async function pickPackSpecAndVersion(versionOptionNamePattern: RegExp) {
  await selectPackSpecification("ps-1");
  await waitFor(() => expect(within(screen.getByLabelText(/^version$/i)).getByRole("option", { name: versionOptionNamePattern })).toBeInTheDocument());
  const version = within(screen.getByLabelText(/^version$/i)).getByRole("option", { name: versionOptionNamePattern }) as HTMLOptionElement;
  fireEvent.change(screen.getByLabelText(/^version$/i), { target: { value: version.value } });
}

describe("PackingPage reconciliation", () => {
  it("6. a balanced 3-way Packing reconciliation allows progression to Review and submission", async () => {
    stubFetch();
    render(withQueryClient(<PackingPage />));
    await addGplToPacking("GA-001");
    await addGplToPacking("GA-002");

    await waitFor(() => expect(screen.getByText(/Pack GA-001, GA-002/)).toBeInTheDocument());
    await pickPackSpecAndVersion(/^v2/);

    // Consumed inputs are seeded from each Lot's own available balance (60 + 40 = 100).
    await waitFor(() => expect(screen.getAllByLabelText(/consumed weight/i)[0]).toHaveValue(60));
    await waitFor(() => expect(screen.getAllByLabelText(/consumed weight/i)[1]).toHaveValue(40));

    fireEvent.change(screen.getByLabelText(/finished goods lot code/i), { target: { value: "FG-001" } });
    fireEvent.change(screen.getByLabelText(/package count/i), { target: { value: "10" } });
    fireEvent.change(screen.getByLabelText(/packed output weight/i), { target: { value: "100" } });

    await waitFor(() => expect(screen.getByText("Balanced")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Review" }));
    await waitFor(() => expect(screen.getByText("Review before recording")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
    await waitFor(() => expect(screen.getByText("Packing recorded")).toBeInTheDocument());
  });

  it("7. an unbalanced Packing reconciliation blocks progression to Review", async () => {
    stubFetch();
    render(withQueryClient(<PackingPage />));
    await addGplToPacking("GA-001");
    await addGplToPacking("GA-002");
    await pickPackSpecAndVersion(/^v2/);
    await waitFor(() => expect(screen.getAllByLabelText(/consumed weight/i)[1]).toHaveValue(40));

    fireEvent.change(screen.getByLabelText(/finished goods lot code/i), { target: { value: "FG-001" } });
    fireEvent.change(screen.getByLabelText(/package count/i), { target: { value: "10" } });
    // Only 50 of the 100 kg consumed is accounted for by the declared output.
    fireEvent.change(screen.getByLabelText(/packed output weight/i), { target: { value: "50" } });

    await waitFor(() => expect(screen.getByText("Out of balance")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Review" }));

    await waitFor(() =>
      expect(screen.getByText(/must equal total consumed input \(100\.000 kg\)/)).toBeInTheDocument(),
    );
    expect(screen.queryByText("Review before recording")).not.toBeInTheDocument();
  });

  it("8. an incompatible (different-Crop) Graded Produce Lot cannot be added once the Packing is Crop-locked", async () => {
    stubFetch();
    render(withQueryClient(<PackingPage />));
    await addGplToPacking("GA-001");

    await waitFor(() => expect(screen.getByText("TM-001")).toBeInTheDocument());
    const otherCropRow = screen.getByText("TM-001").closest("li") as HTMLElement;
    expect(within(otherCropRow).getByRole("button", { name: /add to packing/i })).toBeDisabled();
    expect(
      within(otherCropRow).getByText(/Only Lots matching the Crop already in this Packing can be added/),
    ).toBeInTheDocument();

    // Confirm it genuinely never joined the Packing draft.
    expect(screen.queryByText(/Pack .*TM-001/)).not.toBeInTheDocument();
  });
});

describe("PackingPage effective-time Version selection", () => {
  it("9. a historically-valid RETIRED PackSpecificationVersion is selectable for a backdated effective_time (and DRAFT is never selectable)", async () => {
    stubFetch();
    render(withQueryClient(<PackingPage />));
    await addGplToPacking("GA-001");

    await selectPackSpecification("ps-1");
    await waitFor(() => expect(within(screen.getByLabelText(/^version$/i)).getByRole("option", { name: /^v2/ })).toBeInTheDocument());
    expect(within(screen.getByLabelText(/^version$/i)).queryByRole("option", { name: /^v3/ })).not.toBeInTheDocument();

    fireEvent.change(screen.getByLabelText(/^date$/i), { target: { value: "2025-03-15" } });
    fireEvent.change(screen.getByLabelText(/^time$/i), { target: { value: "12:00" } });

    await waitFor(() =>
      expect(within(screen.getByLabelText(/^version$/i)).getByRole("option", { name: /^v1 — nominal 5\.000 kg/ })).toBeInTheDocument(),
    );
    expect(within(screen.getByLabelText(/^version$/i)).queryByRole("option", { name: /^v2/ })).not.toBeInTheDocument();
    expect(within(screen.getByLabelText(/^version$/i)).queryByRole("option", { name: /^v3/ })).not.toBeInTheDocument();
  });

  it("10. an out-of-window ACTIVE/RETIRED PackSpecificationVersion and a DRAFT Version are both unavailable", async () => {
    stubFetch();
    render(withQueryClient(<PackingPage />));
    await addGplToPacking("GA-001");

    await selectPackSpecification("ps-1");
    await waitFor(() => expect(within(screen.getByLabelText(/^version$/i)).getByRole("option", { name: /^v2/ })).toBeInTheDocument());

    fireEvent.change(screen.getByLabelText(/^date$/i), { target: { value: "2024-01-01" } });
    fireEvent.change(screen.getByLabelText(/^time$/i), { target: { value: "12:00" } });

    await waitFor(() =>
      expect(screen.getByText(/No version of this Pack Specification is valid at the selected effective time/)).toBeInTheDocument(),
    );
    const versionSelect = screen.getByLabelText(/^version$/i);
    expect(within(versionSelect).queryAllByRole("option").filter((o) => (o as HTMLOptionElement).value !== "")).toHaveLength(0);
  });

  it("11. the Pack Specification's nominal net weight never forces the actual packed output weight", async () => {
    stubFetch();
    render(withQueryClient(<PackingPage />));
    await addGplToPacking("GA-001");
    // v2's own nominal_net_weight_kg is 999.000 -- deliberately far from any
    // value typed below, so a coincidental match can't hide forced arithmetic.
    await pickPackSpecAndVersion(/^v2/);

    fireEvent.change(screen.getByLabelText(/package count/i), { target: { value: "3" } });
    fireEvent.change(screen.getByLabelText(/packed output weight/i), { target: { value: "37.5" } });

    expect(screen.getByLabelText(/packed output weight/i)).toHaveValue(37.5);
    // Changing package count afterward must not recompute/overwrite it either.
    fireEvent.change(screen.getByLabelText(/package count/i), { target: { value: "7" } });
    expect(screen.getByLabelText(/packed output weight/i)).toHaveValue(37.5);
  });
});
