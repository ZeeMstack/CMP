import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AppError } from "@/lib/errors/adapter";
import { withQueryClient } from "@/lib/test-utils";

import { VinesProductionTransferForm } from "./VinesProductionTransferForm";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const OVERVIEW = [
  {
    greenhouse_id: "vgh-1", code: "GH-04", name: "Vines Greenhouse", classification: "vines", status: "configured",
    counts: {
      zones: 1, spans: 1, tables: 0, gutters: 2, bag_positions: 40, seeding_stations: 0, germination_chambers: 0,
      seedling_tables: 0, intersalads_tables: 0, intervines_tables: 0, trolleys: 0, trolley_levels: 0,
      trolley_slots: 0, seeding_machines: 0,
    },
  },
];
const STRUCTURE = {
  greenhouse_id: "vgh-1", code: "GH-04", name: "Vines Greenhouse", classification: "vines",
  vines_zones: [
    {
      id: "zone-1", code: "Z1",
      spans: [
        {
          id: "span-1", code: "S1",
          gutters: [
            { id: "gutter-1", code: "GUT-001", bag_position_count: 20 },
            { id: "gutter-2", code: "GUT-002", bag_position_count: 20 },
          ],
        },
      ],
    },
  ],
};
const INTERVINES_PLACEMENTS = [
  {
    batch_id: "batch-1", batch_code: "VIN-0142", crop_id: "crop-1", crop_code: "TOM", crop_common_name: "Tomato",
    variety_id: "var-1", variety_code: "MAR", variety_name: "Marmande",
    table_id: "table-1", table_code: "IV-01", table_name: "IV-01",
    plant_count: 72, earliest_assigned_effective_time: "2026-09-01T00:00:00Z", days_in_intervines: 7,
  },
];
const POOLS_SINGLE = [
  {
    specification_id: "spec-1",
    specification: { id: "spec-1", code: "STD-BAG", name: "Standard Tomato Bag", biological_position_count: 2 },
    available_bag_count: 40, available_position_count: 20, available_plant_capacity: 40,
  },
];

function stubFetch(overrides: Record<string, unknown> = {}) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/farm-setup/greenhouses/vgh-1")) return jsonResponse(overrides.structure ?? STRUCTURE);
      if (url.includes("/farm-setup/greenhouses")) return jsonResponse(overrides.overview ?? OVERVIEW);
      if (url.includes("/nursery/intervines/placements")) return jsonResponse(overrides.intervines ?? INTERVINES_PLACEMENTS);
      if (url.includes("/vines-production/available-grow-bags")) return jsonResponse(overrides.pools ?? POOLS_SINGLE);
      return jsonResponse([]);
    }),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

async function selectSource() {
  fireEvent.focus(screen.getByLabelText(/batch \/ intervines table/i));
  const listbox = await screen.findByRole("listbox");
  fireEvent.click(within(listbox).getByText("IV-01"));
}

async function selectGutter(code: string) {
  await waitFor(() => expect(screen.getByLabelText(/grow gutter/i)).toBeInTheDocument());
  fireEvent.focus(screen.getByLabelText(/grow gutter/i));
  const listbox = await screen.findByRole("listbox");
  fireEvent.click(within(listbox).getByText(code));
  await waitFor(() => expect(screen.getByLabelText(/plants to transfer/i)).toBeInTheDocument());
}

/** The Grow Bag pool query resolves asynchronously after the Gutter is
 * selected -- waiting for its own settled capacity figure (rather than
 * proceeding immediately) avoids racing a plant_count entry/submit against
 * data that genuinely has not arrived yet. */
async function waitForAvailableCapacity(expected: string) {
  await waitFor(() => expect(screen.getByText("Available capacity").nextElementSibling).toHaveTextContent(expected));
}

describe("VinesProductionTransferForm", () => {
  it("renders the source picker for an authorized user", async () => {
    stubFetch();
    render(withQueryClient(<VinesProductionTransferForm farmId="farm-1" onSubmit={vi.fn()} isSubmitting={false} />));
    await waitFor(() => expect(screen.getByLabelText(/batch \/ intervines table/i)).toBeInTheDocument());
  });

  it("establishes the Batch and shows available plants from the selected InterVines source", async () => {
    stubFetch();
    render(withQueryClient(<VinesProductionTransferForm farmId="farm-1" onSubmit={vi.fn()} isSubmitting={false} />));
    await waitFor(() => expect(screen.getByLabelText(/batch \/ intervines table/i)).toBeInTheDocument());
    await selectSource();

    await waitFor(() => expect(screen.getByText("VIN-0142")).toBeInTheDocument());
    expect(screen.getByText(/Tomato \/ Marmande/)).toBeInTheDocument();
    expect(screen.getByText("Available plants").nextElementSibling).toHaveTextContent("72");
  });

  it("auto-selects the single Vines Greenhouse and shows its Gutters", async () => {
    stubFetch();
    render(withQueryClient(<VinesProductionTransferForm farmId="farm-1" onSubmit={vi.fn()} isSubmitting={false} />));
    await waitFor(() => expect(screen.getByLabelText(/batch \/ intervines table/i)).toBeInTheDocument());
    await selectSource();
    await selectGutter("GUT-001");

    await waitFor(() => expect(screen.getByLabelText(/plants to transfer/i)).toBeInTheDocument());
    expect(screen.queryByLabelText(/grow bag specification/i)).not.toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("Available capacity").nextElementSibling).toHaveTextContent("40"));
  });

  it("blocks a plant count exceeding the InterVines source's own available plants", async () => {
    stubFetch();
    render(withQueryClient(<VinesProductionTransferForm farmId="farm-1" onSubmit={vi.fn()} isSubmitting={false} />));
    await waitFor(() => expect(screen.getByLabelText(/batch \/ intervines table/i)).toBeInTheDocument());
    await selectSource();
    await selectGutter("GUT-001");
    fireEvent.change(screen.getByLabelText(/plants to transfer/i), { target: { value: "100" } });

    fireEvent.click(screen.getByRole("button", { name: /transfer 100 plants/i }));
    await waitFor(() => expect(screen.getByText(/exceed this intervines source's available plants/i)).toBeInTheDocument());
    expect(screen.queryByText("Review before transferring")).not.toBeInTheDocument();
  });

  it("blocks a plant count exceeding the available Grow Bag capacity", async () => {
    stubFetch({
      pools: [
        {
          specification_id: "spec-1",
          specification: { id: "spec-1", code: "STD-BAG", name: "Standard Tomato Bag", biological_position_count: 2 },
          available_bag_count: 5, available_position_count: 5, available_plant_capacity: 10,
        },
      ],
    });
    render(withQueryClient(<VinesProductionTransferForm farmId="farm-1" onSubmit={vi.fn()} isSubmitting={false} />));
    await waitFor(() => expect(screen.getByLabelText(/batch \/ intervines table/i)).toBeInTheDocument());
    await selectSource();
    await selectGutter("GUT-001");
    await waitForAvailableCapacity("10");
    fireEvent.change(screen.getByLabelText(/plants to transfer/i), { target: { value: "15" } });

    fireEvent.click(screen.getByRole("button", { name: /transfer 15 plants/i }));
    await waitFor(() => expect(screen.getByText(/exceed the available grow bag capacity/i)).toBeInTheDocument());
  });

  it("submits the exact VinesProductionTransferCreate payload shape on confirm", async () => {
    stubFetch();
    const onSubmit = vi.fn();
    render(withQueryClient(<VinesProductionTransferForm farmId="farm-1" onSubmit={onSubmit} isSubmitting={false} />));
    await waitFor(() => expect(screen.getByLabelText(/batch \/ intervines table/i)).toBeInTheDocument());
    await selectSource();
    await selectGutter("GUT-001");
    await waitForAvailableCapacity("40");
    fireEvent.change(screen.getByLabelText(/plants to transfer/i), { target: { value: "40" } });
    fireEvent.change(screen.getByLabelText(/^date$/i), { target: { value: "2026-09-08" } });
    fireEvent.change(screen.getByLabelText(/^time$/i), { target: { value: "09:00" } });

    fireEvent.click(screen.getByRole("button", { name: /transfer 40 plants/i }));
    await waitFor(() => expect(screen.getByText("Review before transferring")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /confirm transfer/i }));

    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
    const [batchId, payload] = onSubmit.mock.calls[0];
    expect(batchId).toBe("batch-1");
    expect(payload).toMatchObject({
      source_intervines_table_id: "table-1", plant_count: 40, destination_grow_gutter_id: "gutter-1",
      grow_bag_specification_id: "spec-1", note: null,
    });
    expect(typeof payload.client_command_id).toBe("string");
  });

  it("reuses the same client_command_id on an exact retry", async () => {
    stubFetch();
    const onSubmit = vi.fn();
    render(withQueryClient(<VinesProductionTransferForm farmId="farm-1" onSubmit={onSubmit} isSubmitting={false} />));
    await waitFor(() => expect(screen.getByLabelText(/batch \/ intervines table/i)).toBeInTheDocument());
    await selectSource();
    await selectGutter("GUT-001");
    await waitForAvailableCapacity("40");
    fireEvent.change(screen.getByLabelText(/plants to transfer/i), { target: { value: "10" } });

    fireEvent.click(screen.getByRole("button", { name: /transfer 10 plants/i }));
    await waitFor(() => expect(screen.getByText("Review before transferring")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /confirm transfer/i }));
    fireEvent.click(screen.getByRole("button", { name: /confirm transfer/i }));

    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(2));
    expect(onSubmit.mock.calls[0][1].client_command_id).toBe(onSubmit.mock.calls[1][1].client_command_id);
  });

  it("maps a 403 to a permission-denied message with no backend detail leaked", async () => {
    stubFetch();
    render(
      withQueryClient(
        <VinesProductionTransferForm
          farmId="farm-1" onSubmit={vi.fn()} isSubmitting={false}
          serverError={new AppError("permission_error", "insufficient scope: transplant.manage", 403)}
        />,
      ),
    );
    await waitFor(() => expect(screen.getByLabelText(/batch \/ intervines table/i)).toBeInTheDocument());
    expect(screen.getByRole("alert")).toHaveTextContent(/don't have permission/i);
    expect(screen.queryByText(/transplant\.manage/i)).not.toBeInTheDocument();
  });
});
