import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AppError } from "@/lib/errors/adapter";
import { withQueryClient } from "@/lib/test-utils";

import { IntervinesTransplantForm } from "./IntervinesTransplantForm";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const OVERVIEW = [
  {
    greenhouse_id: "gh-1", code: "NUR-01", name: "Nursery", classification: "nursery", status: "configured",
    counts: {
      zones: 0, spans: 0, tables: 0, gutters: 0, bag_positions: 0, seeding_stations: 1, germination_chambers: 1,
      seedling_tables: 3, intersalads_tables: 0, intervines_tables: 2, trolleys: 0, trolley_levels: 0,
      trolley_slots: 0, seeding_machines: 0,
    },
  },
];
const STRUCTURE = {
  greenhouse_id: "gh-1", code: "NUR-01", name: "Nursery", classification: "nursery",
  nursery_intervines: {
    area_id: "area-1",
    tables: [
      { id: "table-1", code: "IV-01", capacity: null },
      { id: "table-2", code: "IV-02", capacity: null },
    ],
  },
};
const TRAYS = [
  {
    batch_id: "batch-1", batch_code: "VIN-0142", tray_id: "tray-1", tray_code: "TRAY-014",
    crop_common_name: "Tomato", variety_name: "Marmande", seed_lot_code: "LOT-1",
    batch_carrier_assignment_id: "assign-1", seedling_entry_id: "entry-1",
    starting_living_seedling_count: 200, total_reduction_magnitude: 20, total_reversal_magnitude: 0,
    current_living_seedling_count: 180, current_source_available_count: 100, checkpoint_count: 0,
    latest_checkpoint_id: null, latest_checkpoint_effective_time: null, latest_checkpoint_remainder_after: null,
    is_depleted: false, event_count: 1, seedling_table_id: "st-1", seedling_table_code: "ST-01",
    assignment_active: true, assignment_released_effective_time: null,
  },
];
const POOLS_SINGLE = [{ specification_id: null, specification: null, available_count: 120 }];
const POOLS_MULTI = [
  {
    specification_id: "spec-1",
    specification: { id: "spec-1", code: "GC-4CM", name: "4cm Rockwool Cube", biological_position_count: 1 },
    available_count: 90,
  },
  {
    specification_id: "spec-2",
    specification: { id: "spec-2", code: "GC-6CM", name: "6cm Rockwool Cube", biological_position_count: 1 },
    available_count: 30,
  },
];

function stubFetch(overrides: Record<string, unknown> = {}) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/farm-setup/greenhouses/gh-1")) return jsonResponse(overrides.structure ?? STRUCTURE);
      if (url.includes("/farm-setup/greenhouses")) return jsonResponse(overrides.overview ?? OVERVIEW);
      if (url.includes("/nursery/seedling/biological-trays")) return jsonResponse(overrides.trays ?? TRAYS);
      if (url.includes("/nursery/intervines/available-grow-cubes")) return jsonResponse(overrides.pools ?? POOLS_SINGLE);
      return jsonResponse([]);
    }),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("IntervinesTransplantForm", () => {
  it("renders the source picker for an authorized user", async () => {
    stubFetch();
    render(withQueryClient(<IntervinesTransplantForm farmId="farm-1" onSubmit={vi.fn()} isSubmitting={false} />));
    await waitFor(() => expect(screen.getByLabelText(/source batch \/ tray/i)).toBeInTheDocument());
  });

  it("establishes the Batch and shows available plants from the selected source Tray", async () => {
    stubFetch();
    render(withQueryClient(<IntervinesTransplantForm farmId="farm-1" onSubmit={vi.fn()} isSubmitting={false} />));
    await waitFor(() => expect(screen.getByLabelText(/source batch \/ tray/i)).toBeInTheDocument());
    fireEvent.focus(screen.getByLabelText(/source batch \/ tray/i));
    const listbox = await screen.findByRole("listbox");
    fireEvent.click(within(listbox).getByText("TRAY-014"));

    await waitFor(() => expect(screen.getByText("VIN-0142")).toBeInTheDocument());
    expect(screen.getByText("Available plants")).toBeInTheDocument();
    expect(screen.getByText("Available plants").nextElementSibling).toHaveTextContent("100");
  });

  it("does not show a Grow Cube specification picker when only one pool exists", async () => {
    stubFetch();
    render(withQueryClient(<IntervinesTransplantForm farmId="farm-1" onSubmit={vi.fn()} isSubmitting={false} />));
    await waitFor(() => expect(screen.getByLabelText(/source batch \/ tray/i)).toBeInTheDocument());
    fireEvent.focus(screen.getByLabelText(/source batch \/ tray/i));
    const listbox = await screen.findByRole("listbox");
    fireEvent.click(within(listbox).getByText("TRAY-014"));

    await waitFor(() => expect(screen.getByLabelText(/intervines table/i)).toBeInTheDocument());
    expect(screen.queryByLabelText(/grow cube specification/i)).not.toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("Available Grow Cubes").nextElementSibling).toHaveTextContent("120"));
  });

  it("shows a Grow Cube specification picker when more than one pool exists", async () => {
    stubFetch({ pools: POOLS_MULTI });
    render(withQueryClient(<IntervinesTransplantForm farmId="farm-1" onSubmit={vi.fn()} isSubmitting={false} />));
    await waitFor(() => expect(screen.getByLabelText(/source batch \/ tray/i)).toBeInTheDocument());
    fireEvent.focus(screen.getByLabelText(/source batch \/ tray/i));
    const listbox = await screen.findByRole("listbox");
    fireEvent.click(within(listbox).getByText("TRAY-014"));

    await waitFor(() => expect(screen.getByLabelText(/grow cube specification/i)).toBeInTheDocument());
    fireEvent.focus(screen.getByLabelText(/grow cube specification/i));
    const specListbox = await screen.findByRole("listbox");
    fireEvent.click(within(specListbox).getByText("GC-4CM"));

    await waitFor(() => expect(screen.getByText("Available Grow Cubes").nextElementSibling).toHaveTextContent("90"));
  });

  it("PILOT-BLOCKER-008 A10: shows 'not configured (effective: 1)' for a null-capacity Table, never 'unlimited'", async () => {
    stubFetch();
    render(withQueryClient(<IntervinesTransplantForm farmId="farm-1" onSubmit={vi.fn()} isSubmitting={false} />));
    await waitFor(() => expect(screen.getByLabelText(/source batch \/ tray/i)).toBeInTheDocument());
    fireEvent.focus(screen.getByLabelText(/source batch \/ tray/i));
    const sourceListbox = await screen.findByRole("listbox");
    fireEvent.click(within(sourceListbox).getByText("TRAY-014"));

    await waitFor(() => expect(screen.getByLabelText(/intervines table/i)).toBeInTheDocument());
    fireEvent.focus(screen.getByLabelText(/intervines table/i));
    const tableListbox = await screen.findByRole("listbox");
    // Both fixture Tables (IV-01, IV-02) have `capacity: null`.
    expect(within(tableListbox).getAllByText(/capacity: not configured \(effective: 1\)/i).length).toBeGreaterThan(0);
    expect(within(tableListbox).queryByText(/unlimited/i)).not.toBeInTheDocument();
  });

  it("blocks a plant count exceeding the source's own available seedlings", async () => {
    stubFetch();
    render(withQueryClient(<IntervinesTransplantForm farmId="farm-1" onSubmit={vi.fn()} isSubmitting={false} />));
    await waitFor(() => expect(screen.getByLabelText(/source batch \/ tray/i)).toBeInTheDocument());
    fireEvent.focus(screen.getByLabelText(/source batch \/ tray/i));
    const listbox = await screen.findByRole("listbox");
    fireEvent.click(within(listbox).getByText("TRAY-014"));

    await waitFor(() => expect(screen.getByLabelText(/intervines table/i)).toBeInTheDocument());
    fireEvent.focus(screen.getByLabelText(/intervines table/i));
    const tableListbox = await screen.findByRole("listbox");
    fireEvent.click(within(tableListbox).getByText("IV-01"));
    fireEvent.change(screen.getByLabelText(/plants to transfer/i), { target: { value: "150" } });

    fireEvent.click(screen.getByRole("button", { name: /transfer 150 plants/i }));
    await waitFor(() => expect(screen.getByText(/exceed this source's available seedlings/i)).toBeInTheDocument());
    expect(screen.queryByText("Review before transplanting")).not.toBeInTheDocument();
  });

  it("blocks a plant count exceeding the available Grow Cubes", async () => {
    stubFetch({ pools: [{ specification_id: null, specification: null, available_count: 20 }] });
    render(withQueryClient(<IntervinesTransplantForm farmId="farm-1" onSubmit={vi.fn()} isSubmitting={false} />));
    await waitFor(() => expect(screen.getByLabelText(/source batch \/ tray/i)).toBeInTheDocument());
    fireEvent.focus(screen.getByLabelText(/source batch \/ tray/i));
    const listbox = await screen.findByRole("listbox");
    fireEvent.click(within(listbox).getByText("TRAY-014"));

    await waitFor(() => expect(screen.getByLabelText(/intervines table/i)).toBeInTheDocument());
    fireEvent.focus(screen.getByLabelText(/intervines table/i));
    const tableListbox = await screen.findByRole("listbox");
    fireEvent.click(within(tableListbox).getByText("IV-01"));
    fireEvent.change(screen.getByLabelText(/plants to transfer/i), { target: { value: "25" } });

    fireEvent.click(screen.getByRole("button", { name: /transfer 25 plants/i }));
    await waitFor(() => expect(screen.getByText(/exceed the available grow cubes/i)).toBeInTheDocument());
  });

  it("submits the exact IntervinesTransplantCreate payload shape on confirm", async () => {
    stubFetch();
    const onSubmit = vi.fn();
    render(withQueryClient(<IntervinesTransplantForm farmId="farm-1" onSubmit={onSubmit} isSubmitting={false} />));
    await waitFor(() => expect(screen.getByLabelText(/source batch \/ tray/i)).toBeInTheDocument());
    fireEvent.focus(screen.getByLabelText(/source batch \/ tray/i));
    const listbox = await screen.findByRole("listbox");
    fireEvent.click(within(listbox).getByText("TRAY-014"));

    await waitFor(() => expect(screen.getByLabelText(/intervines table/i)).toBeInTheDocument());
    fireEvent.focus(screen.getByLabelText(/intervines table/i));
    const tableListbox = await screen.findByRole("listbox");
    fireEvent.click(within(tableListbox).getByText("IV-01"));
    fireEvent.change(screen.getByLabelText(/plants to transfer/i), { target: { value: "72" } });
    fireEvent.change(screen.getByLabelText(/^date$/i), { target: { value: "2026-09-08" } });
    fireEvent.change(screen.getByLabelText(/^time$/i), { target: { value: "09:00" } });

    fireEvent.click(screen.getByRole("button", { name: /transfer 72 plants/i }));
    await waitFor(() => expect(screen.getByText("Review before transplanting")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /confirm transfer/i }));

    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
    const [batchId, payload] = onSubmit.mock.calls[0];
    expect(batchId).toBe("batch-1");
    expect(payload).toMatchObject({
      source_assignment_id: "assign-1", plant_count: 72, destination_location_id: "table-1",
      grow_cube_specification_id: null, note: null,
    });
    expect(typeof payload.client_command_id).toBe("string");
  });

  it("reuses the same client_command_id on an exact retry", async () => {
    stubFetch();
    const onSubmit = vi.fn();
    render(withQueryClient(<IntervinesTransplantForm farmId="farm-1" onSubmit={onSubmit} isSubmitting={false} />));
    await waitFor(() => expect(screen.getByLabelText(/source batch \/ tray/i)).toBeInTheDocument());
    fireEvent.focus(screen.getByLabelText(/source batch \/ tray/i));
    const listbox = await screen.findByRole("listbox");
    fireEvent.click(within(listbox).getByText("TRAY-014"));
    await waitFor(() => expect(screen.getByLabelText(/intervines table/i)).toBeInTheDocument());
    fireEvent.focus(screen.getByLabelText(/intervines table/i));
    const tableListbox = await screen.findByRole("listbox");
    fireEvent.click(within(tableListbox).getByText("IV-01"));
    fireEvent.change(screen.getByLabelText(/plants to transfer/i), { target: { value: "10" } });

    fireEvent.click(screen.getByRole("button", { name: /transfer 10 plants/i }));
    await waitFor(() => expect(screen.getByText("Review before transplanting")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /confirm transfer/i }));
    fireEvent.click(screen.getByRole("button", { name: /confirm transfer/i }));

    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(2));
    expect(onSubmit.mock.calls[0][1].client_command_id).toBe(onSubmit.mock.calls[1][1].client_command_id);
  });

  it("shows generic conflict copy (never raw backend text) for a 409 and forces back to Configure", async () => {
    stubFetch();
    const { rerender } = render(
      withQueryClient(<IntervinesTransplantForm farmId="farm-1" onSubmit={vi.fn()} isSubmitting={false} />),
    );
    await waitFor(() => expect(screen.getByLabelText(/source batch \/ tray/i)).toBeInTheDocument());
    fireEvent.focus(screen.getByLabelText(/source batch \/ tray/i));
    const listbox = await screen.findByRole("listbox");
    fireEvent.click(within(listbox).getByText("TRAY-014"));
    await waitFor(() => expect(screen.getByLabelText(/intervines table/i)).toBeInTheDocument());
    fireEvent.focus(screen.getByLabelText(/intervines table/i));
    const tableListbox = await screen.findByRole("listbox");
    fireEvent.click(within(tableListbox).getByText("IV-01"));
    fireEvent.change(screen.getByLabelText(/plants to transfer/i), { target: { value: "10" } });
    fireEvent.click(screen.getByRole("button", { name: /transfer 10 plants/i }));
    await waitFor(() => expect(screen.getByText("Review before transplanting")).toBeInTheDocument());

    rerender(
      withQueryClient(
        <IntervinesTransplantForm
          farmId="farm-1" onSubmit={vi.fn()} isSubmitting={false}
          serverError={new AppError("conflict", "550e8400-e29b-41d4-a716-446655440000", 409)}
        />,
      ),
    );

    await waitFor(() => expect(screen.queryByText("Review before transplanting")).not.toBeInTheDocument());
    expect(screen.getByLabelText(/source batch \/ tray/i)).toBeInTheDocument();
    expect(screen.queryByText(/550e8400/)).not.toBeInTheDocument();
  });

  it("maps a 403 to a permission-denied message with no backend detail leaked", async () => {
    stubFetch();
    render(
      withQueryClient(
        <IntervinesTransplantForm
          farmId="farm-1" onSubmit={vi.fn()} isSubmitting={false}
          serverError={new AppError("permission_error", "insufficient scope: transplant.manage", 403)}
        />,
      ),
    );
    await waitFor(() => expect(screen.getByLabelText(/source batch \/ tray/i)).toBeInTheDocument());
    expect(screen.getByRole("alert")).toHaveTextContent(/don't have permission/i);
    expect(screen.queryByText(/transplant\.manage/i)).not.toBeInTheDocument();
  });
});
