import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AppError } from "@/lib/errors/adapter";
import { withQueryClient } from "@/lib/test-utils";

import { IntersaladsTransplantForm } from "./IntersaladsTransplantForm";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const OVERVIEW = [
  {
    greenhouse_id: "gh-1", code: "NUR-01", name: "Nursery", classification: "nursery", status: "configured",
    counts: {
      zones: 0, spans: 0, tables: 0, gutters: 0, bag_positions: 0, seeding_stations: 1, germination_chambers: 1,
      seedling_tables: 3, intersalads_tables: 2, intervines_tables: 0, trolleys: 0, trolley_levels: 0,
      trolley_slots: 0, seeding_machines: 0,
    },
  },
];
const STRUCTURE = {
  greenhouse_id: "gh-1", code: "NUR-01", name: "Nursery", classification: "nursery",
  nursery_intersalads: {
    area_id: "area-1",
    tables: [
      { id: "table-1", code: "IS-A-01", capacity: 2 },
      { id: "table-2", code: "IS-A-02", capacity: 1 },
    ],
  },
};
const TRAYS = [
  {
    batch_id: "batch-1", batch_code: "ICE-0142", tray_id: "tray-1", tray_code: "TRAY-014",
    crop_common_name: "Iceberg Lettuce", variety_name: "Mamutik", seed_lot_code: "LOT-1",
    batch_carrier_assignment_id: "assign-1", seedling_entry_id: "entry-1",
    starting_living_seedling_count: 200, total_reduction_magnitude: 20, total_reversal_magnitude: 0,
    current_living_seedling_count: 180, current_source_available_count: 180, checkpoint_count: 0,
    latest_checkpoint_id: null, latest_checkpoint_effective_time: null, latest_checkpoint_remainder_after: null,
    is_depleted: false, event_count: 1, seedling_table_id: "st-1", seedling_table_code: "ST-01",
    assignment_active: true, assignment_released_effective_time: null,
  },
  {
    batch_id: "batch-1", batch_code: "ICE-0142", tray_id: "tray-2", tray_code: "TRAY-015",
    crop_common_name: "Iceberg Lettuce", variety_name: "Mamutik", seed_lot_code: "LOT-1",
    batch_carrier_assignment_id: "assign-2", seedling_entry_id: "entry-2",
    starting_living_seedling_count: 100, total_reduction_magnitude: 0, total_reversal_magnitude: 0,
    current_living_seedling_count: 100, current_source_available_count: 100, checkpoint_count: 0,
    latest_checkpoint_id: null, latest_checkpoint_effective_time: null, latest_checkpoint_remainder_after: null,
    is_depleted: false, event_count: 0, seedling_table_id: "st-1", seedling_table_code: "ST-01",
    assignment_active: true, assignment_released_effective_time: null,
  },
  {
    batch_id: "batch-2", batch_code: "ICE-0200", tray_id: "tray-3", tray_code: "TRAY-090",
    crop_common_name: "Iceberg Lettuce", variety_name: "Frostbite", seed_lot_code: "LOT-2",
    batch_carrier_assignment_id: "assign-3", seedling_entry_id: "entry-3",
    starting_living_seedling_count: 50, total_reduction_magnitude: 0, total_reversal_magnitude: 0,
    current_living_seedling_count: 50, current_source_available_count: 50, checkpoint_count: 0,
    latest_checkpoint_id: null, latest_checkpoint_effective_time: null, latest_checkpoint_remainder_after: null,
    is_depleted: false, event_count: 0, seedling_table_id: "st-2", seedling_table_code: "ST-02",
    assignment_active: true, assignment_released_effective_time: null,
  },
];
const PLATES = [
  { id: "plate-1", code: "NP-001", status: "active", specification_id: "spec-1", specification: { id: "spec-1", code: "NCP-200", name: "200 Hole Plate", biological_position_count: 200 } },
  { id: "plate-2", code: "NP-002", status: "active", specification_id: "spec-1", specification: { id: "spec-1", code: "NCP-200", name: "200 Hole Plate", biological_position_count: 200 } },
];

function stubFetch(overrides: Record<string, unknown> = {}) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/farm-setup/greenhouses/gh-1")) return jsonResponse(overrides.structure ?? STRUCTURE);
      if (url.includes("/farm-setup/greenhouses")) return jsonResponse(overrides.overview ?? OVERVIEW);
      if (url.includes("/nursery/seedling/biological-trays")) return jsonResponse(overrides.trays ?? TRAYS);
      if (url.includes("/nursery/intersalads/available-plates")) return jsonResponse(overrides.plates ?? PLATES);
      if (url.includes("/locations/table-1/occupants")) {
        return jsonResponse(
          (overrides.occupantsByLocation as Record<string, unknown>)?.["table-1"] ??
            { target: { kind: "location", id: "table-1" }, active_occupancies: [] },
        );
      }
      if (url.includes("/locations/table-2/occupants")) {
        return jsonResponse(
          (overrides.occupantsByLocation as Record<string, unknown>)?.["table-2"] ??
            { target: { kind: "location", id: "table-2" }, active_occupancies: [] },
        );
      }
      if (url.includes("/occupants")) return jsonResponse({ target: { kind: "location", id: "unknown" }, active_occupancies: [] });
      return jsonResponse([]);
    }),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

async function addSource(_trayLabel: RegExp, matchLabel: string) {
  fireEvent.focus(screen.getByLabelText(/add a source tray/i));
  const listbox = await screen.findByRole("listbox");
  await waitFor(() => expect(within(listbox).getByText(matchLabel)).toBeInTheDocument());
  fireEvent.click(within(listbox).getByText(matchLabel));
}

/** Every destination card lives in its own `<li>` keyed by its "Destination
 * N" heading -- scoping queries `within` that card keeps multi-destination
 * tests unambiguous instead of relying on "last element in the array". */
function destinationCard(n: number): HTMLElement {
  return screen.getByText(`Destination ${n}`).closest("li") as HTMLElement;
}

async function addDestinationWithPlateAndTable(plateCode: string, tableCode: string) {
  fireEvent.click(screen.getByRole("button", { name: /add destination plate/i }));
  const count = screen.getAllByText(/^Destination \d+$/).length;
  const card = destinationCard(count);

  fireEvent.focus(within(card).getByLabelText(/^Plate for destination/i));
  const plateListbox = await screen.findByRole("listbox");
  await waitFor(() => expect(within(plateListbox).getByText(plateCode)).toBeInTheDocument());
  fireEvent.click(within(plateListbox).getByText(plateCode));

  fireEvent.focus(within(card).getByLabelText(/^Table for destination/i));
  const tableListbox = await screen.findByRole("listbox");
  await waitFor(() => expect(within(tableListbox).getByText(tableCode)).toBeInTheDocument());
  fireEvent.click(within(tableListbox).getByText(tableCode));
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

describe("IntersaladsTransplantForm", () => {
  it("renders the source picker for an authorized user", async () => {
    stubFetch();
    render(withQueryClient(<IntersaladsTransplantForm farmId="farm-1" onSubmit={vi.fn()} isSubmitting={false} />));
    await waitFor(() => expect(screen.getByLabelText(/add a source tray/i)).toBeInTheDocument());
  });

  it("establishes the Batch from the first source Tray selected", async () => {
    stubFetch();
    render(withQueryClient(<IntersaladsTransplantForm farmId="farm-1" onSubmit={vi.fn()} isSubmitting={false} />));
    await waitFor(() => expect(screen.getByLabelText(/add a source tray/i)).toBeInTheDocument());
    await addSource(/TRAY-014/, "TRAY-014");
    await waitFor(() => expect(screen.getByText("ICE-0142")).toBeInTheDocument());
    expect(screen.getByText(/Iceberg Lettuce \/ Mamutik/)).toBeInTheDocument();
  });

  it("only offers additional source Trays from the same Batch once one is established", async () => {
    stubFetch();
    render(withQueryClient(<IntersaladsTransplantForm farmId="farm-1" onSubmit={vi.fn()} isSubmitting={false} />));
    await waitFor(() => expect(screen.getByLabelText(/add a source tray/i)).toBeInTheDocument());
    await addSource(/TRAY-014/, "TRAY-014");

    fireEvent.focus(screen.getByLabelText(/add a source tray/i));
    await waitFor(() => expect(screen.getByText("TRAY-015")).toBeInTheDocument());
    expect(screen.queryByText("TRAY-090")).not.toBeInTheDocument();
  });

  it("supports multiple source Trays from the same Batch in one draft", async () => {
    stubFetch();
    render(withQueryClient(<IntersaladsTransplantForm farmId="farm-1" onSubmit={vi.fn()} isSubmitting={false} />));
    await waitFor(() => expect(screen.getByLabelText(/add a source tray/i)).toBeInTheDocument());
    await addSource(/TRAY-014/, "TRAY-014");
    await addSource(/TRAY-015/, "TRAY-015");
    expect(screen.getByText("TRAY-014")).toBeInTheDocument();
    expect(screen.getByText("TRAY-015")).toBeInTheDocument();
  });

  it("adds and removes a destination Plate", async () => {
    stubFetch();
    render(withQueryClient(<IntersaladsTransplantForm farmId="farm-1" onSubmit={vi.fn()} isSubmitting={false} />));
    await waitFor(() => expect(screen.getByLabelText(/add a source tray/i)).toBeInTheDocument());
    await addSource(/TRAY-014/, "TRAY-014");
    await addDestinationWithPlateAndTable("NP-001", "IS-A-01");
    const destinationHeading = screen.getByText("Destination 1");
    expect(destinationHeading).toBeInTheDocument();
    const destinationCard = destinationHeading.closest("li") as HTMLElement;

    fireEvent.click(within(destinationCard).getByRole("button", { name: /^remove$/i }));
    expect(screen.queryByText("Destination 1")).not.toBeInTheDocument();
  });

  it("derives the assigned count from source allocations, never a typed field", async () => {
    stubFetch();
    render(withQueryClient(<IntersaladsTransplantForm farmId="farm-1" onSubmit={vi.fn()} isSubmitting={false} />));
    await waitFor(() => expect(screen.getByLabelText(/add a source tray/i)).toBeInTheDocument());
    await addSource(/TRAY-014/, "TRAY-014");
    await addDestinationWithPlateAndTable("NP-001", "IS-A-01");

    await addAllocationToDestination(1, "TRAY-014", 80);
    await waitFor(() => expect(screen.getByText("Assigned to Plate").nextElementSibling).toHaveTextContent("80"));
  });

  it("blocks a duplicate Plate used as two separate destinations", async () => {
    stubFetch();
    render(withQueryClient(<IntersaladsTransplantForm farmId="farm-1" onSubmit={vi.fn()} isSubmitting={false} />));
    await waitFor(() => expect(screen.getByLabelText(/add a source tray/i)).toBeInTheDocument());
    await addSource(/TRAY-014/, "TRAY-014");
    await addDestinationWithPlateAndTable("NP-001", "IS-A-01");

    // The already-used Plate must not appear again in the picker for a
    // second destination row.
    fireEvent.click(screen.getByRole("button", { name: /add destination plate/i }));
    const plateSelects = screen.getAllByLabelText(/^Plate for destination/i);
    fireEvent.focus(plateSelects[plateSelects.length - 1]);
    await waitFor(() => expect(screen.getByText("NP-002", { selector: "span" })).toBeInTheDocument());
    expect(screen.queryByText("NP-001", { selector: "span" })).not.toBeInTheDocument();
  });

  it("blocks Review when no source Tray is selected", async () => {
    stubFetch();
    render(withQueryClient(<IntersaladsTransplantForm farmId="farm-1" onSubmit={vi.fn()} isSubmitting={false} />));
    await waitFor(() => expect(screen.getByLabelText(/add a source tray/i)).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Review" })).toBeDisabled();
  });

  it("requires other_loss_note when other_loss_count is greater than 0", async () => {
    stubFetch();
    render(withQueryClient(<IntersaladsTransplantForm farmId="farm-1" onSubmit={vi.fn()} isSubmitting={false} />));
    await waitFor(() => expect(screen.getByLabelText(/add a source tray/i)).toBeInTheDocument());
    await addSource(/TRAY-014/, "TRAY-014");
    await addDestinationWithPlateAndTable("NP-001", "IS-A-01");
    await addAllocationToDestination(1, "TRAY-014", 150);

    fireEvent.click(screen.getByText(/losses during transplant/i));
    const otherInputs = screen.getAllByLabelText(/^other$/i);
    fireEvent.change(otherInputs[otherInputs.length - 1], { target: { value: "5" } });

    fireEvent.click(screen.getByRole("button", { name: "Review" }));
    await waitFor(() => expect(screen.getByText(/note is required/i)).toBeInTheDocument());
  });

  it("submits the exact IntersaladsTransplantCreate payload shape on confirm", async () => {
    stubFetch();
    const onSubmit = vi.fn();
    render(withQueryClient(<IntersaladsTransplantForm farmId="farm-1" onSubmit={onSubmit} isSubmitting={false} />));
    await waitFor(() => expect(screen.getByLabelText(/add a source tray/i)).toBeInTheDocument());
    await addSource(/TRAY-014/, "TRAY-014");
    await addDestinationWithPlateAndTable("NP-001", "IS-A-01");
    await addAllocationToDestination(1, "TRAY-014", 150);
    fireEvent.change(screen.getByLabelText(/^date$/i), { target: { value: "2026-08-22" } });
    fireEvent.change(screen.getByLabelText(/^time$/i), { target: { value: "09:00" } });

    fireEvent.click(screen.getByRole("button", { name: "Review" }));
    await waitFor(() => expect(screen.getByText("Review before transplanting")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Confirm transplant" }));

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
  });

  it("reuses the same client_command_id on an exact retry", async () => {
    stubFetch();
    const onSubmit = vi.fn();
    render(withQueryClient(<IntersaladsTransplantForm farmId="farm-1" onSubmit={onSubmit} isSubmitting={false} />));
    await waitFor(() => expect(screen.getByLabelText(/add a source tray/i)).toBeInTheDocument());
    await addSource(/TRAY-014/, "TRAY-014");
    await addDestinationWithPlateAndTable("NP-001", "IS-A-01");
    await addAllocationToDestination(1, "TRAY-014", 150);

    fireEvent.click(screen.getByRole("button", { name: "Review" }));
    await waitFor(() => expect(screen.getByText("Review before transplanting")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Confirm transplant" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm transplant" }));

    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(2));
    expect(onSubmit.mock.calls[0][1].client_command_id).toBe(onSubmit.mock.calls[1][1].client_command_id);
  });

  it("shows generic conflict copy (never raw backend text) for a 409 and forces back to Configure", async () => {
    stubFetch();
    const { rerender } = render(
      withQueryClient(<IntersaladsTransplantForm farmId="farm-1" onSubmit={vi.fn()} isSubmitting={false} />),
    );
    await waitFor(() => expect(screen.getByLabelText(/add a source tray/i)).toBeInTheDocument());
    await addSource(/TRAY-014/, "TRAY-014");
    await addDestinationWithPlateAndTable("NP-001", "IS-A-01");
    await addAllocationToDestination(1, "TRAY-014", 150);
    fireEvent.click(screen.getByRole("button", { name: "Review" }));
    await waitFor(() => expect(screen.getByText("Review before transplanting")).toBeInTheDocument());

    // A 409 newly arrives (as it would after a real failed submit) --
    // this is the realistic trigger, not an error present from mount.
    rerender(
      withQueryClient(
        <IntersaladsTransplantForm
          farmId="farm-1" onSubmit={vi.fn()} isSubmitting={false}
          serverError={new AppError("conflict", "550e8400-e29b-41d4-a716-446655440000", 409)}
        />,
      ),
    );

    // The 409's raw message here is a bare id -- never shown verbatim.
    await waitFor(() => expect(screen.queryByText("Review before transplanting")).not.toBeInTheDocument());
    // Forced back to Configure -- the source picker is visible again.
    expect(screen.getByLabelText(/add a source tray/i)).toBeInTheDocument();
    expect(screen.queryByText(/550e8400/)).not.toBeInTheDocument();
  });

  it("shows the backend's own detail text for a non-conflict, non-UUID error", async () => {
    stubFetch();
    render(
      withQueryClient(
        <IntersaladsTransplantForm
          farmId="farm-1" onSubmit={vi.fn()} isSubmitting={false}
          serverError={new AppError("invalid_request", "other_loss_note is required when other_loss_count > 0", 422)}
        />,
      ),
    );
    await waitFor(() => expect(screen.getByLabelText(/add a source tray/i)).toBeInTheDocument());
    await addSource(/TRAY-014/, "TRAY-014");
    await addDestinationWithPlateAndTable("NP-001", "IS-A-01");
    await addAllocationToDestination(1, "TRAY-014", 150);
    fireEvent.click(screen.getByRole("button", { name: "Review" }));

    // 422 does not force back to Configure -- stays on Review for the
    // operator to see the detail against their own entered data.
    await waitFor(() => expect(screen.getByText("Review before transplanting")).toBeInTheDocument());
    expect(screen.getByRole("alert")).toHaveTextContent(/other_loss_note is required/i);
  });

  it("keeps the same client_command_id going Back from Review without editing anything, then resubmitting", async () => {
    stubFetch();
    const onSubmit = vi.fn();
    render(withQueryClient(<IntersaladsTransplantForm farmId="farm-1" onSubmit={onSubmit} isSubmitting={false} />));
    await waitFor(() => expect(screen.getByLabelText(/add a source tray/i)).toBeInTheDocument());
    await addSource(/TRAY-014/, "TRAY-014");
    await addDestinationWithPlateAndTable("NP-001", "IS-A-01");
    await addAllocationToDestination(1, "TRAY-014", 150);
    fireEvent.click(screen.getByRole("button", { name: "Review" }));
    await waitFor(() => expect(screen.getByText("Review before transplanting")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Confirm transplant" }));
    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
    const firstId = onSubmit.mock.calls[0][1].client_command_id;

    // Back without changing anything, then straight back to Review and
    // resubmit -- the id must NOT rotate merely because Back was clicked.
    fireEvent.click(screen.getByRole("button", { name: "Back" }));
    fireEvent.click(screen.getByRole("button", { name: "Review" }));
    await waitFor(() => expect(screen.getByText("Review before transplanting")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Confirm transplant" }));
    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(2));
    expect(onSubmit.mock.calls[1][1].client_command_id).toBe(firstId);
  });

  it("rotates client_command_id only when the payload materially changes after a submit", async () => {
    stubFetch();
    const onSubmit = vi.fn();
    render(withQueryClient(<IntersaladsTransplantForm farmId="farm-1" onSubmit={onSubmit} isSubmitting={false} />));
    await waitFor(() => expect(screen.getByLabelText(/add a source tray/i)).toBeInTheDocument());
    await addSource(/TRAY-014/, "TRAY-014");
    await addDestinationWithPlateAndTable("NP-001", "IS-A-01");
    await addAllocationToDestination(1, "TRAY-014", 150);
    fireEvent.click(screen.getByRole("button", { name: "Review" }));
    await waitFor(() => expect(screen.getByText("Review before transplanting")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Confirm transplant" }));
    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
    const firstId = onSubmit.mock.calls[0][1].client_command_id;

    // Go back and materially change the allocated quantity before
    // resubmitting -- the id MUST rotate this time.
    fireEvent.click(screen.getByRole("button", { name: "Back" }));
    fireEvent.change(screen.getByLabelText(/quantity for allocation 1/i), { target: { value: "160" } });
    fireEvent.click(screen.getByRole("button", { name: "Review" }));
    await waitFor(() => expect(screen.getByText("Review before transplanting")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Confirm transplant" }));
    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(2));
    expect(onSubmit.mock.calls[1][1].client_command_id).not.toBe(firstId);
    expect(onSubmit.mock.calls[1][1].allocations[0].allocated_plant_count).toBe(160);
  });

  // --- PRE-COMMIT AUDIT section 16: high-value N x M / capacity / balance / error coverage ---

  it("supports one source feeding multiple destinations", async () => {
    stubFetch();
    render(withQueryClient(<IntersaladsTransplantForm farmId="farm-1" onSubmit={vi.fn()} isSubmitting={false} />));
    await waitFor(() => expect(screen.getByLabelText(/add a source tray/i)).toBeInTheDocument());
    await addSource(/TRAY-014/, "TRAY-014");
    await addDestinationWithPlateAndTable("NP-001", "IS-A-01");
    await addDestinationWithPlateAndTable("NP-002", "IS-A-02");
    await addAllocationToDestination(1, "TRAY-014", 80);
    await addAllocationToDestination(2, "TRAY-014", 60);

    await waitFor(() =>
      expect(screen.getByText("Available").nextElementSibling).toHaveTextContent("180"),
    );
    expect(screen.getByText("Allocated").nextElementSibling).toHaveTextContent("140");
    expect(screen.getByText("Remaining").nextElementSibling).toHaveTextContent("40");
  });

  it("supports one destination receiving multiple same-Batch sources", async () => {
    stubFetch();
    render(withQueryClient(<IntersaladsTransplantForm farmId="farm-1" onSubmit={vi.fn()} isSubmitting={false} />));
    await waitFor(() => expect(screen.getByLabelText(/add a source tray/i)).toBeInTheDocument());
    await addSource(/TRAY-014/, "TRAY-014");
    await addSource(/TRAY-015/, "TRAY-015");
    await addDestinationWithPlateAndTable("NP-001", "IS-A-01");
    await addAllocationToDestination(1, "TRAY-014", 80);
    await addAllocationToDestination(1, "TRAY-015", 50);

    await waitFor(() => expect(screen.getByText("Assigned to Plate").nextElementSibling).toHaveTextContent("130"));

    // Per-source totals in the "Source Seedling Tray(s)" section must also
    // reflect both allocations correctly -- not just the destination's own
    // combined total.
    const tray014Row = screen.getByText("TRAY-014").closest("li") as HTMLElement;
    expect(within(tray014Row).getByText("Allocated").nextElementSibling).toHaveTextContent("80");
    const tray015Row = screen.getByText("TRAY-015").closest("li") as HTMLElement;
    expect(within(tray015Row).getByText("Allocated").nextElementSibling).toHaveTextContent("50");
  });

  it("computes per-source Allocated totals correctly when an explicit Nursery Greenhouse selection happens between adding sources and allocating", async () => {
    // Mirrors a real multi-greenhouse Farm: the explicit "Nursery" <select>
    // step (never exercised by any other test in this file, whose fixture
    // always has exactly one greenhouse and auto-selects it) happens in
    // between adding the source Trays and adding the destination/
    // allocations -- proving that state transition doesn't corrupt the
    // per-source "Allocated" computation.
    stubFetch({
      overview: [
        ...OVERVIEW,
        {
          greenhouse_id: "gh-2", code: "NUR-02", name: "Nursery Two", classification: "nursery", status: "configured",
          counts: {
            zones: 0, spans: 0, tables: 0, gutters: 0, bag_positions: 0, seeding_stations: 1, germination_chambers: 1,
            seedling_tables: 2, intersalads_tables: 1, intervines_tables: 0, trolleys: 0, trolley_levels: 0,
            trolley_slots: 0, seeding_machines: 0,
          },
        },
      ],
    });
    render(withQueryClient(<IntersaladsTransplantForm farmId="farm-1" onSubmit={vi.fn()} isSubmitting={false} />));
    await waitFor(() => expect(screen.getByLabelText(/add a source tray/i)).toBeInTheDocument());
    await addSource(/TRAY-014/, "TRAY-014");
    await addSource(/TRAY-015/, "TRAY-015");

    const nurserySelect = screen.getByLabelText(/^nursery$/i);
    fireEvent.change(nurserySelect, { target: { value: "gh-1" } });
    await waitFor(() => expect(screen.getByRole("button", { name: /add destination plate/i })).toBeInTheDocument());

    await addDestinationWithPlateAndTable("NP-001", "IS-A-01");
    await addAllocationToDestination(1, "TRAY-014", 80);
    await addAllocationToDestination(1, "TRAY-015", 50);

    await waitFor(() => expect(screen.getByText("Assigned to Plate").nextElementSibling).toHaveTextContent("130"));
    const tray014Row = screen.getByText("TRAY-014").closest("li") as HTMLElement;
    expect(within(tray014Row).getByText("Allocated").nextElementSibling).toHaveTextContent("80");
    const tray015Row = screen.getByText("TRAY-015").closest("li") as HTMLElement;
    expect(within(tray015Row).getByText("Allocated").nextElementSibling).toHaveTextContent("50");
  });

  it("keeps showing a destination's own selected Plate after further edits (Plate must not disappear from its own picker's options)", async () => {
    stubFetch();
    render(withQueryClient(<IntersaladsTransplantForm farmId="farm-1" onSubmit={vi.fn()} isSubmitting={false} />));
    await waitFor(() => expect(screen.getByLabelText(/add a source tray/i)).toBeInTheDocument());
    await addSource(/TRAY-014/, "TRAY-014");
    await addDestinationWithPlateAndTable("NP-001", "IS-A-01");
    await addAllocationToDestination(1, "TRAY-014", 80);

    const plateInput = within(destinationCard(1)).getByLabelText(/^Plate for destination/i);
    expect(plateInput).toHaveValue("NP-001");

    fireEvent.click(screen.getByRole("button", { name: /add destination plate/i }));
    expect(plateInput).toHaveValue("NP-001");
  });

  it("submits the exact request body for a multi-source/multi-destination command", async () => {
    stubFetch();
    const onSubmit = vi.fn();
    render(withQueryClient(<IntersaladsTransplantForm farmId="farm-1" onSubmit={onSubmit} isSubmitting={false} />));
    await waitFor(() => expect(screen.getByLabelText(/add a source tray/i)).toBeInTheDocument());
    await addSource(/TRAY-014/, "TRAY-014");
    await addSource(/TRAY-015/, "TRAY-015");
    await addDestinationWithPlateAndTable("NP-001", "IS-A-01");
    await addDestinationWithPlateAndTable("NP-002", "IS-A-02");
    await addAllocationToDestination(1, "TRAY-014", 80);
    await addAllocationToDestination(1, "TRAY-015", 20);
    await addAllocationToDestination(2, "TRAY-014", 60);

    fireEvent.click(screen.getByRole("button", { name: "Review" }));
    await waitFor(() => expect(screen.getByText("Review before transplanting")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Confirm transplant" }));
    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));

    const [, payload] = onSubmit.mock.calls[0];
    expect(payload.source_lines.map((l: { source_assignment_id: string }) => l.source_assignment_id)).toEqual([
      "assign-1", "assign-2",
    ]);
    expect(payload.destination_lines).toEqual([
      { destination_carrier_id: "plate-1", assigned_plant_count: 100, destination_location_id: "table-1", note: null },
      { destination_carrier_id: "plate-2", assigned_plant_count: 60, destination_location_id: "table-2", note: null },
    ]);
    expect(payload.allocations).toEqual([
      { source_assignment_id: "assign-1", destination_carrier_id: "plate-1", allocated_plant_count: 80 },
      { source_assignment_id: "assign-2", destination_carrier_id: "plate-1", allocated_plant_count: 20 },
      { source_assignment_id: "assign-1", destination_carrier_id: "plate-2", allocated_plant_count: 60 },
    ]);
  });

  it("allows a destination assigned count exactly at Plate capacity", async () => {
    stubFetch({
      plates: [
        { id: "plate-1", code: "NP-001", status: "active", specification_id: "spec-1", specification: { id: "spec-1", code: "NCP-180", name: "180 Hole Plate", biological_position_count: 180 } },
      ],
    });
    const onSubmit = vi.fn();
    render(withQueryClient(<IntersaladsTransplantForm farmId="farm-1" onSubmit={onSubmit} isSubmitting={false} />));
    await waitFor(() => expect(screen.getByLabelText(/add a source tray/i)).toBeInTheDocument());
    await addSource(/TRAY-014/, "TRAY-014");
    await addDestinationWithPlateAndTable("NP-001", "IS-A-01");
    await addAllocationToDestination(1, "TRAY-014", 180);

    fireEvent.click(screen.getByRole("button", { name: "Review" }));
    await waitFor(() => expect(screen.getByText("Review before transplanting")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Confirm transplant" }));
    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
  });

  it("blocks a destination assigned count one over Plate capacity", async () => {
    stubFetch({
      plates: [
        { id: "plate-1", code: "NP-001", status: "active", specification_id: "spec-1", specification: { id: "spec-1", code: "NCP-180", name: "180 Hole Plate", biological_position_count: 180 } },
      ],
    });
    render(withQueryClient(<IntersaladsTransplantForm farmId="farm-1" onSubmit={vi.fn()} isSubmitting={false} />));
    await waitFor(() => expect(screen.getByLabelText(/add a source tray/i)).toBeInTheDocument());
    await addSource(/TRAY-014/, "TRAY-014");
    await addDestinationWithPlateAndTable("NP-001", "IS-A-01");
    await addAllocationToDestination(1, "TRAY-014", 179);
    // 179 for TRAY-014 leaves only 1 available -- top up with TRAY-015 to
    // push the destination's own assigned total 1 over the Plate's capacity
    // without over-allocating any single source.
    await addSource(/TRAY-015/, "TRAY-015");
    await addAllocationToDestination(1, "TRAY-015", 2);

    fireEvent.click(screen.getByRole("button", { name: "Review" }));
    await waitFor(() => expect(screen.getByText(/exceeds this Plate's capacity/i)).toBeInTheDocument());
    expect(screen.queryByText("Review before transplanting")).not.toBeInTheDocument();
  });

  it("includes transplant-boundary losses in the source-balance preview and blocks over-allocation", async () => {
    stubFetch();
    render(withQueryClient(<IntersaladsTransplantForm farmId="farm-1" onSubmit={vi.fn()} isSubmitting={false} />));
    await waitFor(() => expect(screen.getByLabelText(/add a source tray/i)).toBeInTheDocument());
    await addSource(/TRAY-014/, "TRAY-014");
    await addDestinationWithPlateAndTable("NP-001", "IS-A-01");
    await addAllocationToDestination(1, "TRAY-014", 170);

    fireEvent.click(screen.getByText(/losses during transplant/i));
    fireEvent.change(screen.getByLabelText(/^damage$/i), { target: { value: "5" } });
    fireEvent.change(screen.getByLabelText(/^qc rejected$/i), { target: { value: "3" } });
    fireEvent.change(screen.getByLabelText(/^sample$/i), { target: { value: "2" } });

    // 180 available - 170 allocated - 10 losses = 0 remaining.
    await waitFor(() => expect(screen.getByText("Remaining").nextElementSibling).toHaveTextContent("0"));

    // One more unit of loss now pushes remaining negative -- blocked.
    fireEvent.change(screen.getByLabelText(/^sample$/i), { target: { value: "3" } });
    fireEvent.click(screen.getByRole("button", { name: "Review" }));
    await waitFor(() => expect(screen.getByText(/exceeds this source's available seedlings/i)).toBeInTheDocument());
    expect(screen.queryByText("Review before transplanting")).not.toBeInTheDocument();
  });

  it("shows a full source exhaustion preview (remaining = 0) and lets it reach Review", async () => {
    stubFetch();
    const onSubmit = vi.fn();
    render(withQueryClient(<IntersaladsTransplantForm farmId="farm-1" onSubmit={onSubmit} isSubmitting={false} />));
    await waitFor(() => expect(screen.getByLabelText(/add a source tray/i)).toBeInTheDocument());
    await addSource(/TRAY-014/, "TRAY-014");
    await addDestinationWithPlateAndTable("NP-001", "IS-A-01");
    await addAllocationToDestination(1, "TRAY-014", 180);

    await waitFor(() => expect(screen.getByText("Remaining").nextElementSibling).toHaveTextContent("0"));
    fireEvent.click(screen.getByRole("button", { name: "Review" }));
    await waitFor(() => expect(screen.getByText("Review before transplanting")).toBeInTheDocument());
    expect(screen.getByText(/Remaining 0/)).toBeInTheDocument();
  });

  it("accounts for server occupants plus every same-Table destination already in the draft", async () => {
    stubFetch({
      occupantsByLocation: {
        // table-2 (IS-A-02) has capacity 1 and already has 1 active occupant.
        "table-2": {
          target: { kind: "location", id: "table-2" },
          active_occupancies: [{ id: "occ-1", tenant_id: "t", farm_id: "f", target_location_id: "table-2" }],
        },
      },
    });
    render(withQueryClient(<IntersaladsTransplantForm farmId="farm-1" onSubmit={vi.fn()} isSubmitting={false} />));
    await waitFor(() => expect(screen.getByLabelText(/add a source tray/i)).toBeInTheDocument());
    await addSource(/TRAY-014/, "TRAY-014");
    await addDestinationWithPlateAndTable("NP-001", "IS-A-02");
    await addAllocationToDestination(1, "TRAY-014", 50);

    await waitFor(() =>
      expect(screen.getByText(/exceed its known capacity/i)).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByRole("button", { name: "Review" }));
    expect(screen.queryByText("Review before transplanting")).not.toBeInTheDocument();
  });

  it("disables the confirm action while a submit is pending", async () => {
    stubFetch();
    render(withQueryClient(<IntersaladsTransplantForm farmId="farm-1" onSubmit={vi.fn()} isSubmitting={true} />));
    await waitFor(() => expect(screen.getByLabelText(/add a source tray/i)).toBeInTheDocument());
    await addSource(/TRAY-014/, "TRAY-014");
    await addDestinationWithPlateAndTable("NP-001", "IS-A-01");
    await addAllocationToDestination(1, "TRAY-014", 150);
    fireEvent.click(screen.getByRole("button", { name: "Review" }));
    await waitFor(() => expect(screen.getByText("Review before transplanting")).toBeInTheDocument());

    expect(screen.getByRole("button", { name: "Transplanting…" })).toBeDisabled();
  });

  it("maps a 403 to a permission-denied message with no backend detail leaked", async () => {
    stubFetch();
    render(
      withQueryClient(
        <IntersaladsTransplantForm
          farmId="farm-1" onSubmit={vi.fn()} isSubmitting={false}
          serverError={new AppError("permission_error", "insufficient scope: transplant.manage", 403)}
        />,
      ),
    );
    await waitFor(() => expect(screen.getByLabelText(/add a source tray/i)).toBeInTheDocument());
    expect(screen.getByRole("alert")).toHaveTextContent(/don't have permission/i);
    expect(screen.queryByText(/transplant\.manage/i)).not.toBeInTheDocument();
  });

  it("preserves the draft's source and destination selections after a conflict forces Configure", async () => {
    stubFetch();
    const { rerender } = render(
      withQueryClient(<IntersaladsTransplantForm farmId="farm-1" onSubmit={vi.fn()} isSubmitting={false} />),
    );
    await waitFor(() => expect(screen.getByLabelText(/add a source tray/i)).toBeInTheDocument());
    await addSource(/TRAY-014/, "TRAY-014");
    await addDestinationWithPlateAndTable("NP-001", "IS-A-01");
    await addAllocationToDestination(1, "TRAY-014", 150);
    fireEvent.click(screen.getByRole("button", { name: "Review" }));
    await waitFor(() => expect(screen.getByText("Review before transplanting")).toBeInTheDocument());

    rerender(
      withQueryClient(
        <IntersaladsTransplantForm
          farmId="farm-1" onSubmit={vi.fn()} isSubmitting={false}
          serverError={new AppError("conflict", "plate-1", 409)}
        />,
      ),
    );
    await waitFor(() => expect(screen.getByLabelText(/add a source tray/i)).toBeInTheDocument());

    // Forced back to Configure, but the draft itself is untouched -- the
    // source row and destination card are both still populated.
    expect(screen.getByText("TRAY-014")).toBeInTheDocument();
    expect(destinationCard(1)).toBeInTheDocument();
    expect(within(destinationCard(1)).getByText("Assigned to Plate").nextElementSibling).toHaveTextContent("150");
  });
});
