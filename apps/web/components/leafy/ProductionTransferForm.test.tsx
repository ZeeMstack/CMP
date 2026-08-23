import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { withQueryClient } from "@/lib/test-utils";

import { ProductionTransferForm } from "./ProductionTransferForm";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const OVERVIEW = [
  {
    greenhouse_id: "lgh-1", code: "LEAFY-01", name: "Leafy", classification: "leafy_greens", status: "configured",
    counts: {
      zones: 2, spans: 2, tables: 3, gutters: 0, bag_positions: 0, seeding_stations: 0, germination_chambers: 0,
      seedling_tables: 0, intersalads_tables: 0, intervines_tables: 0, trolleys: 0, trolley_levels: 0,
      trolley_slots: 0, seeding_machines: 0,
    },
  },
];
const STRUCTURE = {
  greenhouse_id: "lgh-1", code: "LEAFY-01", name: "Leafy", classification: "leafy_greens",
  leafy_zones: [
    {
      id: "zone-1", code: "Z01",
      spans: [{ id: "span-1", code: "S01", tables: [{ id: "table-1", code: "T01", capacity: 2 }, { id: "table-2", code: "T02", capacity: 1 }] }],
    },
    {
      id: "zone-2", code: "Z02",
      spans: [{ id: "span-2", code: "S02", tables: [{ id: "table-3", code: "T03", capacity: 1 }] }],
    },
  ],
};
const SOURCES = [
  {
    source_assignment_id: "assign-1", batch_id: "batch-1", batch_code: "ICE-0142",
    crop: { id: "crop-1", code: "ICE", common_name: "Iceberg Lettuce" },
    variety: { id: "var-1", code: "MAM", name: "Mamutik" },
    carrier: { id: "carrier-1", code: "NP-014", carrier_type: { id: "ct-1", code: "nursery_cultivation_plate", name: "Nursery Cultivation Plate" } },
    authoritative_available_count: 180,
    current_location: { id: "table-is-1", code: "IS-A-01", name: "IS-A-01", location_type_code: "intersalads_table" },
  },
  {
    source_assignment_id: "assign-2", batch_id: "batch-1", batch_code: "ICE-0142",
    crop: { id: "crop-1", code: "ICE", common_name: "Iceberg Lettuce" },
    variety: { id: "var-1", code: "MAM", name: "Mamutik" },
    carrier: { id: "carrier-2", code: "NP-015", carrier_type: { id: "ct-1", code: "nursery_cultivation_plate", name: "Nursery Cultivation Plate" } },
    authoritative_available_count: 100,
    current_location: null,
  },
  {
    source_assignment_id: "assign-3", batch_id: "batch-2", batch_code: "ICE-0200",
    crop: { id: "crop-1", code: "ICE", common_name: "Iceberg Lettuce" },
    variety: { id: "var-2", code: "FRO", name: "Frostbite" },
    carrier: { id: "carrier-3", code: "NP-090", carrier_type: { id: "ct-1", code: "nursery_cultivation_plate", name: "Nursery Cultivation Plate" } },
    authoritative_available_count: 50,
    current_location: null,
  },
];
const PLATES = [
  { id: "plate-1", code: "PP-001", status: "active", specification_id: "spec-1", specification: { id: "spec-1", code: "PP-200", name: "200 Hole Plate", biological_position_count: 200 } },
  { id: "plate-2", code: "PP-002", status: "active", specification_id: "spec-1", specification: { id: "spec-1", code: "PP-200", name: "200 Hole Plate", biological_position_count: 200 } },
];

// Correction ticket (multi-Greenhouse default + cross-Greenhouse
// independence tests) fixtures: two Leafy Greenhouses, each with its own
// minimal one-Table structure.
const ZERO_COUNTS = {
  zones: 1, spans: 1, tables: 1, gutters: 0, bag_positions: 0, seeding_stations: 0, germination_chambers: 0,
  seedling_tables: 0, intersalads_tables: 0, intervines_tables: 0, trolleys: 0, trolley_levels: 0,
  trolley_slots: 0, seeding_machines: 0,
};
const OVERVIEW_MULTI_GH = [
  { greenhouse_id: "lgh-a", code: "GH-A", name: "Leafy A", classification: "leafy_greens", status: "configured", counts: ZERO_COUNTS },
  { greenhouse_id: "lgh-b", code: "GH-B", name: "Leafy B", classification: "leafy_greens", status: "configured", counts: ZERO_COUNTS },
];
const STRUCTURE_A = {
  greenhouse_id: "lgh-a", code: "GH-A", name: "Leafy A", classification: "leafy_greens",
  leafy_zones: [{ id: "a-zone-1", code: "AZ01", spans: [{ id: "a-span-1", code: "AS01", tables: [{ id: "a-table-1", code: "AT01", capacity: 5 }] }] }],
};
const STRUCTURE_B = {
  greenhouse_id: "lgh-b", code: "GH-B", name: "Leafy B", classification: "leafy_greens",
  leafy_zones: [{ id: "b-zone-1", code: "BZ01", spans: [{ id: "b-span-1", code: "BS01", tables: [{ id: "b-table-1", code: "BT01", capacity: 5 }] }] }],
};

function stubFetch(overrides: Record<string, unknown> = {}) {
  // `structures` keys by greenhouse id (default: the single fixture
  // Greenhouse `lgh-1`) so multi-Greenhouse tests can register a second
  // Greenhouse's own structure without disturbing every other test.
  const structures = (overrides.structures as Record<string, unknown>) ?? { "lgh-1": STRUCTURE };
  // `occupantsByLocation` keys by Table (location) id -- default: no
  // server-side occupants for any Table, matching the prior fixed stub.
  const occupantsByLocation = (overrides.occupantsByLocation as Record<string, unknown[]>) ?? {};
  // BROWSER QA CORRECTION 3: a real occupants fetch takes real network
  // latency; the default stub resolves synchronously, which cannot stress
  // the same async-timing path a real browser exercises. Tests that need
  // to prove the capacity check still converges under realistic staggered
  // resolution (not just instant mock resolution) can opt into a delay.
  const occupantsDelayMs = (overrides.occupantsDelayMs as number | undefined) ?? 0;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      const structureMatch = url.match(/\/farm-setup\/greenhouses\/([^/?]+)/);
      if (structureMatch && structures[structureMatch[1]]) return jsonResponse(structures[structureMatch[1]]);
      if (url.includes("/farm-setup/greenhouses")) return jsonResponse(overrides.overview ?? OVERVIEW);
      if (url.includes("/leafy-production/available-sources")) return jsonResponse(overrides.sources ?? SOURCES);
      if (url.includes("/leafy-production/available-plates")) return jsonResponse(overrides.plates ?? PLATES);
      const occupantsMatch = url.match(/\/locations\/([^/]+)\/occupants/);
      if (occupantsMatch) {
        if (occupantsDelayMs > 0) await new Promise((resolve) => setTimeout(resolve, occupantsDelayMs));
        return jsonResponse({
          target: { kind: "location", id: occupantsMatch[1] },
          active_occupancies: occupantsByLocation[occupantsMatch[1]] ?? [],
        });
      }
      return jsonResponse([]);
    }),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

async function addSource(matchLabel: string) {
  fireEvent.focus(screen.getByLabelText(/add a source nursery plate/i));
  const listbox = await screen.findByRole("listbox");
  await waitFor(() => expect(within(listbox).getByText(matchLabel)).toBeInTheDocument());
  fireEvent.click(within(listbox).getByText(matchLabel));
}

function destinationCard(n: number): HTMLElement {
  return screen.getByText(`Destination ${n}`).closest("li") as HTMLElement;
}

async function pickInField(card: HTMLElement, labelPattern: RegExp, matchLabel: string) {
  fireEvent.focus(within(card).getByLabelText(labelPattern));
  const listbox = await screen.findByRole("listbox");
  await waitFor(() => expect(within(listbox).getByText(matchLabel)).toBeInTheDocument());
  fireEvent.click(within(listbox).getByText(matchLabel));
}

async function addDestinationWithFullPlacement(plateCode: string, zoneCode: string, spanCode: string, tableCode: string) {
  fireEvent.click(screen.getByRole("button", { name: /add destination production plate/i }));
  const count = screen.getAllByText(/^Destination \d+$/).length;
  const card = destinationCard(count);

  await pickInField(card, /^Plate for destination/i, plateCode);
  await pickInField(card, /^Zone$/i, zoneCode);
  await pickInField(card, /^Span$/i, spanCode);
  await pickInField(card, /^Table$/i, tableCode);
}

async function addAllocationToDestination(n: number, sourceCode: string, quantity: number) {
  const card = destinationCard(n);
  fireEvent.click(within(card).getByRole("button", { name: /add source allocation/i }));

  const pickers = within(card).getAllByLabelText(/^Source for allocation/i);
  fireEvent.focus(pickers[pickers.length - 1]);
  const listbox = await screen.findByRole("listbox");
  await waitFor(() => expect(within(listbox).getByText(sourceCode)).toBeInTheDocument());
  fireEvent.click(within(listbox).getByText(sourceCode));

  const qtyInputs = within(card).getAllByLabelText(/^Quantity for allocation/i);
  fireEvent.change(qtyInputs[qtyInputs.length - 1], { target: { value: String(quantity) } });
}

describe("ProductionTransferForm", () => {
  it("renders the source picker for an authorized user", async () => {
    stubFetch();
    render(withQueryClient(<ProductionTransferForm farmId="farm-1" onSubmit={vi.fn()} isSubmitting={false} />));
    await waitFor(() => expect(screen.getByLabelText(/add a source nursery plate/i)).toBeInTheDocument());
  });

  it("establishes the Batch from the first source Plate selected", async () => {
    stubFetch();
    render(withQueryClient(<ProductionTransferForm farmId="farm-1" onSubmit={vi.fn()} isSubmitting={false} />));
    await waitFor(() => expect(screen.getByLabelText(/add a source nursery plate/i)).toBeInTheDocument());
    await addSource("NP-014");
    await waitFor(() => expect(screen.getByText("ICE-0142")).toBeInTheDocument());
    expect(screen.getByText(/Iceberg Lettuce \/ Mamutik/)).toBeInTheDocument();
  });

  it("only offers additional source Plates from the same Batch once one is established", async () => {
    stubFetch();
    render(withQueryClient(<ProductionTransferForm farmId="farm-1" onSubmit={vi.fn()} isSubmitting={false} />));
    await waitFor(() => expect(screen.getByLabelText(/add a source nursery plate/i)).toBeInTheDocument());
    await addSource("NP-014");

    fireEvent.focus(screen.getByLabelText(/add a source nursery plate/i));
    await waitFor(() => expect(screen.getByText("NP-015")).toBeInTheDocument());
    expect(screen.queryByText("NP-090")).not.toBeInTheDocument();
  });

  it("displays current physical location as informational context, not a filter", async () => {
    stubFetch();
    render(withQueryClient(<ProductionTransferForm farmId="farm-1" onSubmit={vi.fn()} isSubmitting={false} />));
    await waitFor(() => expect(screen.getByLabelText(/add a source nursery plate/i)).toBeInTheDocument());
    await addSource("NP-014");
    await waitFor(() => expect(screen.getByText(/currently at is-a-01/i)).toBeInTheDocument());
  });

  it("cascades Zone -> Span -> Table, resetting descendants when an ancestor changes", async () => {
    stubFetch();
    render(withQueryClient(<ProductionTransferForm farmId="farm-1" onSubmit={vi.fn()} isSubmitting={false} />));
    await waitFor(() => expect(screen.getByLabelText(/add a source nursery plate/i)).toBeInTheDocument());
    await addSource("NP-014");
    fireEvent.click(screen.getByRole("button", { name: /add destination production plate/i }));
    const card = destinationCard(1);

    await pickInField(card, /^Plate for destination/i, "PP-001");
    await pickInField(card, /^Zone$/i, "Z01");
    await pickInField(card, /^Span$/i, "S01");
    await pickInField(card, /^Table$/i, "T01");
    await waitFor(() => expect(within(card).getByText(/LEAFY-01 \/ Z01 \/ S01 \/ T01/)).toBeInTheDocument());

    // Changing Zone resets Span and Table -- T01's ancestry label must
    // disappear, and the new Zone's own Span (S02) must be selectable.
    await pickInField(card, /^Zone$/i, "Z02");
    expect(within(card).queryByText(/LEAFY-01 \/ Z01/)).not.toBeInTheDocument();
    await pickInField(card, /^Span$/i, "S02");
    await pickInField(card, /^Table$/i, "T03");
    await waitFor(() => expect(within(card).getByText(/LEAFY-01 \/ Z02 \/ S02 \/ T03/)).toBeInTheDocument());
  });

  it("derives the assigned count from source allocations, never a typed field", async () => {
    stubFetch();
    render(withQueryClient(<ProductionTransferForm farmId="farm-1" onSubmit={vi.fn()} isSubmitting={false} />));
    await waitFor(() => expect(screen.getByLabelText(/add a source nursery plate/i)).toBeInTheDocument());
    await addSource("NP-014");
    await addDestinationWithFullPlacement("PP-001", "Z01", "S01", "T01");

    await addAllocationToDestination(1, "NP-014", 80);
    await waitFor(() => expect(screen.getByText("Assigned to Plate").nextElementSibling).toHaveTextContent("80"));
  });

  it("blocks a duplicate Plate used as two separate destinations", async () => {
    stubFetch();
    render(withQueryClient(<ProductionTransferForm farmId="farm-1" onSubmit={vi.fn()} isSubmitting={false} />));
    await waitFor(() => expect(screen.getByLabelText(/add a source nursery plate/i)).toBeInTheDocument());
    await addSource("NP-014");
    await addDestinationWithFullPlacement("PP-001", "Z01", "S01", "T01");

    fireEvent.click(screen.getByRole("button", { name: /add destination production plate/i }));
    const plateSelects = screen.getAllByLabelText(/^Plate for destination/i);
    fireEvent.focus(plateSelects[plateSelects.length - 1]);
    await waitFor(() => expect(screen.getByText("PP-002", { selector: "span" })).toBeInTheDocument());
    expect(screen.queryByText("PP-001", { selector: "span" })).not.toBeInTheDocument();
  });

  it("blocks Review when no source Plate is selected", async () => {
    stubFetch();
    render(withQueryClient(<ProductionTransferForm farmId="farm-1" onSubmit={vi.fn()} isSubmitting={false} />));
    await waitFor(() => expect(screen.getByLabelText(/add a source nursery plate/i)).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Review" })).toBeDisabled();
  });

  it("requires other_loss_note when other_loss_count is greater than 0", async () => {
    stubFetch();
    render(withQueryClient(<ProductionTransferForm farmId="farm-1" onSubmit={vi.fn()} isSubmitting={false} />));
    await waitFor(() => expect(screen.getByLabelText(/add a source nursery plate/i)).toBeInTheDocument());
    await addSource("NP-014");
    await addDestinationWithFullPlacement("PP-001", "Z01", "S01", "T01");
    await addAllocationToDestination(1, "NP-014", 150);

    fireEvent.click(screen.getByText(/losses during transfer/i));
    const otherInputs = screen.getAllByLabelText(/^other$/i);
    fireEvent.change(otherInputs[otherInputs.length - 1], { target: { value: "5" } });

    fireEvent.click(screen.getByRole("button", { name: "Review" }));
    await waitFor(() => expect(screen.getByText(/note is required/i)).toBeInTheDocument());
  });

  it("submits the exact LeafyProductionTransferCreate payload shape on confirm", async () => {
    stubFetch();
    const onSubmit = vi.fn();
    render(withQueryClient(<ProductionTransferForm farmId="farm-1" onSubmit={onSubmit} isSubmitting={false} />));
    await waitFor(() => expect(screen.getByLabelText(/add a source nursery plate/i)).toBeInTheDocument());
    await addSource("NP-014");
    await addDestinationWithFullPlacement("PP-001", "Z01", "S01", "T01");
    await addAllocationToDestination(1, "NP-014", 150);
    fireEvent.change(screen.getByLabelText(/^date$/i), { target: { value: "2026-08-22" } });
    fireEvent.change(screen.getByLabelText(/^time$/i), { target: { value: "09:00" } });

    fireEvent.click(screen.getByRole("button", { name: "Review" }));
    await waitFor(() => expect(screen.getByText("Review before transferring")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Confirm transfer" }));

    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
    const [batchId, payload] = onSubmit.mock.calls[0];
    expect(batchId).toBe("batch-1");
    expect(payload.source_lines).toEqual([
      {
        source_assignment_id: "assign-1", transplant_damage_count: 0, qc_rejection_count: 0, sample_count: 0,
        other_loss_count: 0, other_loss_note: null, note: null,
      },
    ]);
    expect(payload.destination_lines).toEqual([
      { destination_carrier_id: "plate-1", assigned_plant_count: 150, destination_location_id: "table-1", note: null },
    ]);
    expect(payload.allocations).toEqual([
      { source_assignment_id: "assign-1", destination_carrier_id: "plate-1", allocated_plant_count: 150 },
    ]);
    expect(typeof payload.client_command_id).toBe("string");
  });

  it("reuses the same client_command_id on an unchanged retry, rotates it after an edit", async () => {
    stubFetch();
    const onSubmit = vi.fn();
    render(withQueryClient(<ProductionTransferForm farmId="farm-1" onSubmit={onSubmit} isSubmitting={false} />));
    await waitFor(() => expect(screen.getByLabelText(/add a source nursery plate/i)).toBeInTheDocument());
    await addSource("NP-014");
    await addDestinationWithFullPlacement("PP-001", "Z01", "S01", "T01");
    await addAllocationToDestination(1, "NP-014", 150);
    fireEvent.change(screen.getByLabelText(/^date$/i), { target: { value: "2026-08-22" } });
    fireEvent.change(screen.getByLabelText(/^time$/i), { target: { value: "09:00" } });

    fireEvent.click(screen.getByRole("button", { name: "Review" }));
    await waitFor(() => expect(screen.getByText("Review before transferring")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Confirm transfer" }));
    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
    const firstId = onSubmit.mock.calls[0][1].client_command_id as string;

    // Back to Configure without editing, then submit again -- same id.
    fireEvent.click(screen.getByRole("button", { name: "Back" }));
    await waitFor(() => expect(screen.getByRole("button", { name: /add destination production plate/i })).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Review" }));
    await waitFor(() => expect(screen.getByText("Review before transferring")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Confirm transfer" }));
    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(2));
    expect(onSubmit.mock.calls[1][1].client_command_id).toBe(firstId);

    // Edit the quantity, then submit -- id must rotate.
    fireEvent.click(screen.getByRole("button", { name: "Back" }));
    await waitFor(() => expect(screen.getByRole("button", { name: /add destination production plate/i })).toBeInTheDocument());
    const qtyInputs = screen.getAllByLabelText(/^Quantity for allocation/i);
    fireEvent.change(qtyInputs[qtyInputs.length - 1], { target: { value: "100" } });
    fireEvent.click(screen.getByRole("button", { name: "Review" }));
    await waitFor(() => expect(screen.getByText("Review before transferring")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Confirm transfer" }));
    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(3));
    expect(onSubmit.mock.calls[2][1].client_command_id).not.toBe(firstId);
  });

  // --- PRE-COMMIT AUDIT CORRECTION 1: real Table-capacity data flow ---

  it("reports a known-capacity conflict when server occupancy plus the draft would exceed a Table's capacity", async () => {
    stubFetch({ occupantsByLocation: { "table-1": [{ id: "occ-1" }] } });
    render(withQueryClient(<ProductionTransferForm farmId="farm-1" onSubmit={vi.fn()} isSubmitting={false} />));
    await waitFor(() => expect(screen.getByLabelText(/add a source nursery plate/i)).toBeInTheDocument());
    await addSource("NP-014");
    // table-1 has capacity 2; one server occupant already there, and two
    // draft destinations both targeting it, pushes the known total to 3.
    await addDestinationWithFullPlacement("PP-001", "Z01", "S01", "T01");
    await addDestinationWithFullPlacement("PP-002", "Z01", "S01", "T01");

    await waitFor(() =>
      expect(
        screen.getByText(/One of the selected Leafy Tables would exceed its known capacity with this draft/i),
      ).toBeInTheDocument(),
    );
  });

  it("does not warn when server occupancy plus the draft is within a Table's capacity", async () => {
    stubFetch(); // no server occupants anywhere
    render(withQueryClient(<ProductionTransferForm farmId="farm-1" onSubmit={vi.fn()} isSubmitting={false} />));
    await waitFor(() => expect(screen.getByLabelText(/add a source nursery plate/i)).toBeInTheDocument());
    await addSource("NP-014");
    // table-1 has capacity 2; zero server occupants, two draft destinations
    // -- exactly at capacity, not over it.
    await addDestinationWithFullPlacement("PP-001", "Z01", "S01", "T01");
    await addDestinationWithFullPlacement("PP-002", "Z01", "S01", "T01");

    const card2 = destinationCard(2);
    await waitFor(() => expect(within(card2).getByText("Table occupants (server)")).toBeInTheDocument());
    expect(
      screen.queryByText(/One of the selected Leafy Tables would exceed its known capacity with this draft/i),
    ).not.toBeInTheDocument();
  });

  it("clears a stale Table's reported capacity from validation once the operator moves off that Table", async () => {
    stubFetch({ occupantsByLocation: { "table-1": [{ id: "occ-1" }, { id: "occ-2" }] } });
    render(withQueryClient(<ProductionTransferForm farmId="farm-1" onSubmit={vi.fn()} isSubmitting={false} />));
    await waitFor(() => expect(screen.getByLabelText(/add a source nursery plate/i)).toBeInTheDocument());
    await addSource("NP-014");
    // table-1: capacity 2, 2 server occupants already, 1 draft destination
    // -- known total 3, over capacity.
    await addDestinationWithFullPlacement("PP-001", "Z01", "S01", "T01");
    await waitFor(() =>
      expect(
        screen.getByText(/One of the selected Leafy Tables would exceed its known capacity with this draft/i),
      ).toBeInTheDocument(),
    );

    // Moving the same destination to a different Zone clears its Table
    // selection -- the previously-reported (still cached) capacity for
    // table-1 must stop participating in the check entirely.
    const card = destinationCard(1);
    await pickInField(card, /^Zone$/i, "Z02");

    await waitFor(() =>
      expect(
        screen.queryByText(/One of the selected Leafy Tables would exceed its known capacity with this draft/i),
      ).not.toBeInTheDocument(),
    );
  });

  // --- BROWSER QA CORRECTION 2: exact reported real-browser sequence ---
  // (capacity=1, same Table, two destinations, zero server occupants, no
  // allocations entered yet) -- reproduced twice: once with the default
  // synchronous stub, once with a realistic occupants-fetch delay, since
  // the reported browser defect could not be reproduced with instant
  // resolution alone and a staggered/async timing path deserves its own
  // proof rather than assuming synchronous coverage generalizes to it.

  it("warns for capacity=1 when two destinations target the same Table with zero server occupants (exact reported sequence)", async () => {
    stubFetch();
    render(withQueryClient(<ProductionTransferForm farmId="farm-1" onSubmit={vi.fn()} isSubmitting={false} />));
    await waitFor(() => expect(screen.getByLabelText(/add a source nursery plate/i)).toBeInTheDocument());
    await addSource("NP-014");
    // table-2 has capacity 1; zero server occupants; two draft destinations
    // both target it, without either having a source allocation yet --
    // physical Plate occupancy of a Table is not conditional on biological
    // allocation having been entered.
    await addDestinationWithFullPlacement("PP-001", "Z01", "S01", "T02");
    await addDestinationWithFullPlacement("PP-002", "Z01", "S01", "T02");

    await waitFor(() =>
      expect(
        screen.getByText(/One of the selected Leafy Tables would exceed its known capacity with this draft/i),
      ).toBeInTheDocument(),
    );
  });

  it("warns for capacity=1 with two same-Table destinations even under realistic occupants-fetch latency", async () => {
    stubFetch({ occupantsDelayMs: 50 });
    render(withQueryClient(<ProductionTransferForm farmId="farm-1" onSubmit={vi.fn()} isSubmitting={false} />));
    await waitFor(() => expect(screen.getByLabelText(/add a source nursery plate/i)).toBeInTheDocument());
    await addSource("NP-014");
    await addDestinationWithFullPlacement("PP-001", "Z01", "S01", "T02");
    await addDestinationWithFullPlacement("PP-002", "Z01", "S01", "T02");

    await waitFor(
      () =>
        expect(
          screen.getByText(/One of the selected Leafy Tables would exceed its known capacity with this draft/i),
        ).toBeInTheDocument(),
      { timeout: 3000 },
    );
  });

  it("does not warn when two destinations with the same capacity-1 Table code target genuinely different Tables", async () => {
    stubFetch();
    render(withQueryClient(<ProductionTransferForm farmId="farm-1" onSubmit={vi.fn()} isSubmitting={false} />));
    await waitFor(() => expect(screen.getByLabelText(/add a source nursery plate/i)).toBeInTheDocument());
    await addSource("NP-014");
    // table-2 (T02, capacity 1) and table-1 (T01, capacity 2) are different
    // Tables -- one destination on each must never be treated as sharing
    // occupancy.
    await addDestinationWithFullPlacement("PP-001", "Z01", "S01", "T02");
    await addDestinationWithFullPlacement("PP-002", "Z01", "S01", "T01");

    const card2 = destinationCard(2);
    await waitFor(() => expect(within(card2).getByText("Table occupants (server)")).toBeInTheDocument());
    expect(
      screen.queryByText(/One of the selected Leafy Tables would exceed its known capacity with this draft/i),
    ).not.toBeInTheDocument();
  });

  // --- PRE-COMMIT AUDIT CORRECTION 1: Greenhouse carry-forward default ---

  it("defaults a new destination's Greenhouse to the previous destination's, but lets the operator change it independently", async () => {
    stubFetch({ overview: OVERVIEW_MULTI_GH, structures: { "lgh-a": STRUCTURE_A, "lgh-b": STRUCTURE_B } });
    render(withQueryClient(<ProductionTransferForm farmId="farm-1" onSubmit={vi.fn()} isSubmitting={false} />));
    await waitFor(() => expect(screen.getByLabelText(/add a source nursery plate/i)).toBeInTheDocument());
    await addSource("NP-014");

    fireEvent.click(screen.getByRole("button", { name: /add destination production plate/i }));
    const card1 = destinationCard(1);
    fireEvent.change(within(card1).getByLabelText(/leafy greenhouse/i), { target: { value: "lgh-b" } });

    fireEvent.click(screen.getByRole("button", { name: /add destination production plate/i }));
    const card2 = destinationCard(2);
    await waitFor(() => expect(within(card2).getByLabelText(/leafy greenhouse/i)).toHaveValue("lgh-b"));

    // The operator can still change destination 2's Greenhouse ...
    fireEvent.change(within(card2).getByLabelText(/leafy greenhouse/i), { target: { value: "lgh-a" } });
    await waitFor(() => expect(within(card2).getByLabelText(/leafy greenhouse/i)).toHaveValue("lgh-a"));

    // ... without affecting destination 1's own Greenhouse (cross-Greenhouse
    // destinations in one command must remain possible -- no global state).
    expect(within(card1).getByLabelText(/leafy greenhouse/i)).toHaveValue("lgh-b");
  });
});
