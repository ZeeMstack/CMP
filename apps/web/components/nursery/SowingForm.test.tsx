import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { withQueryClient } from "@/lib/test-utils";

import { SowingForm } from "./SowingForm";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const NURSERY_OVERVIEW = [
  {
    greenhouse_id: "gh-1", code: "NUR-01", name: "Nursery", classification: "nursery", status: "configured",
    counts: {
      zones: 0, spans: 0, tables: 0, gutters: 0, bag_positions: 0, seeding_stations: 1, germination_chambers: 1,
      seedling_tables: 3, intersalads_tables: 0, intervines_tables: 0, trolleys: 0, trolley_levels: 0,
      trolley_slots: 0, seeding_machines: 0,
    },
  },
];
const NURSERY_STRUCTURE = {
  greenhouse_id: "gh-1", code: "NUR-01", name: "Nursery", classification: "nursery",
  nursery_seeding_stations: [{ id: "station-1", code: "SEED-01", name: "Seeding Station" }],
};
const SEED_LOTS = [
  {
    id: "lot-1", tenant_id: "t", farm_id: "f", code: "RZ-MAM-2026-001",
    crop: { id: "crop-1", code: "ICE", common_name: "Iceberg Lettuce" },
    variety: { id: "var-1", code: "MAM", name: "Mamutik" },
    supplier_name: null, supplier_lot_reference: null, received_date: null, expiry_date: null,
    status: "active", created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z",
  },
];
const AVAILABLE_TRAYS = [
  { id: "tray-1", code: "ST-0001", carrier_type: { id: "ct-1", code: "seed_tray", name: "Seed Tray" } },
  { id: "tray-2", code: "ST-0002", carrier_type: { id: "ct-1", code: "seed_tray", name: "Seed Tray" } },
];

function stubFetch(overrides: Record<string, unknown> = {}) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/farm-setup/greenhouses/gh-1")) return jsonResponse(overrides.structure ?? NURSERY_STRUCTURE);
      if (url.includes("/farm-setup/greenhouses")) return jsonResponse(overrides.overview ?? NURSERY_OVERVIEW);
      if (url.includes("/seed-lots")) return jsonResponse(overrides.seedLots ?? SEED_LOTS);
      if (url.includes("/nursery/seed-trays/available")) return jsonResponse(overrides.trays ?? AVAILABLE_TRAYS);
      if (url.includes("/assets")) return jsonResponse(overrides.machines ?? []);
      return jsonResponse([]);
    }),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

async function selectNurseryAndSeedLot() {
  await waitFor(() => expect(screen.getByText("NUR-01")).toBeInTheDocument());
  fireEvent.change(screen.getByLabelText(/^nursery$/i), { target: { value: "gh-1" } });
  await waitFor(() => expect(screen.getByDisplayValue("SEED-01")).toBeInTheDocument());
  fireEvent.change(screen.getByLabelText(/seed lot/i), { target: { value: "lot-1" } });
}

describe("SowingForm", () => {
  it("shows an empty state for available trays when none exist", async () => {
    stubFetch({ trays: [] });
    render(withQueryClient(<SowingForm farmId="farm-1" onSubmit={vi.fn()} isSubmitting={false} />));
    await waitFor(() => expect(screen.getByText("NUR-01")).toBeInTheDocument());
    const traySelect = screen.getByLabelText(/add a seed tray/i);
    expect(traySelect).toBeInTheDocument();
    expect(screen.queryByText("ST-0001")).not.toBeInTheDocument();
  });

  it("resolves the Seeding Station automatically once a Nursery is selected", async () => {
    stubFetch();
    render(withQueryClient(<SowingForm farmId="farm-1" onSubmit={vi.fn()} isSubmitting={false} />));
    await waitFor(() => expect(screen.getByText("NUR-01")).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText(/^nursery$/i), { target: { value: "gh-1" } });
    await waitFor(() => expect(screen.getByDisplayValue("SEED-01")).toBeInTheDocument());
  });

  it("shows an actionable configuration message when the Nursery has no Seeding Station", async () => {
    stubFetch({ structure: { greenhouse_id: "gh-1", code: "NUR-01", name: "Nursery", classification: "nursery", nursery_seeding_stations: [] } });
    render(withQueryClient(<SowingForm farmId="farm-1" onSubmit={vi.fn()} isSubmitting={false} />));
    await waitFor(() => expect(screen.getByText("NUR-01")).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText(/^nursery$/i), { target: { value: "gh-1" } });
    await waitFor(() =>
      expect(screen.getByDisplayValue("This Nursery has no Seeding Station configured")).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByRole("button", { name: "Review" }));
    await waitFor(() => expect(screen.getByText(/seeding station is required/i)).toBeInTheDocument());
  });

  it("never silently picks a Seeding Station when a Nursery has more than one -- requires an explicit operator choice", async () => {
    stubFetch({
      structure: {
        greenhouse_id: "gh-1", code: "NUR-01", name: "Nursery", classification: "nursery",
        nursery_seeding_stations: [
          { id: "station-1", code: "SEED-01", name: "Seeding Station 1" },
          { id: "station-2", code: "SEED-02", name: "Seeding Station 2" },
        ],
      },
    });
    const onSubmit = vi.fn();
    render(withQueryClient(<SowingForm farmId="farm-1" onSubmit={onSubmit} isSubmitting={false} />));
    await waitFor(() => expect(screen.getByText("NUR-01")).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText(/^nursery$/i), { target: { value: "gh-1" } });
    await waitFor(() => expect(screen.getByLabelText(/^seeding station$/i).tagName).toBe("SELECT"));

    // Neither station is pre-selected; Review is blocked until one is chosen.
    const stationSelect = screen.getByLabelText(/^seeding station$/i) as HTMLSelectElement;
    expect(stationSelect.value).toBe("");
    fireEvent.change(screen.getByLabelText(/seed lot/i), { target: { value: "lot-1" } });
    fireEvent.click(screen.getByRole("button", { name: "Review" }));
    await waitFor(() => expect(screen.getByText(/seeding station is required/i)).toBeInTheDocument());

    fireEvent.change(stationSelect, { target: { value: "station-2" } });
    fireEvent.change(screen.getByLabelText(/add a seed tray/i), { target: { value: "tray-1" } });
    await waitFor(() => expect(screen.getByText("ST-0001")).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText(/seeds sown for st-0001/i), { target: { value: "200" } });
    fireEvent.click(screen.getByRole("button", { name: "Review" }));
    await waitFor(() => expect(screen.getByText("Review before sowing")).toBeInTheDocument());
    expect(screen.getByText("SEED-02")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Sow" }));
    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
    expect(onSubmit.mock.calls[0][0].seeding_station_id).toBe("station-2");
  });

  it("adds a tray, prevents selecting it twice, and computes the running total", async () => {
    stubFetch();
    render(withQueryClient(<SowingForm farmId="farm-1" onSubmit={vi.fn()} isSubmitting={false} />));
    await selectNurseryAndSeedLot();

    fireEvent.change(screen.getByLabelText(/add a seed tray/i), { target: { value: "tray-1" } });
    await waitFor(() => expect(screen.getByText("ST-0001")).toBeInTheDocument());

    // The already-selected tray must not appear again in the picker.
    const picker = screen.getByLabelText(/add a seed tray/i) as HTMLSelectElement;
    const optionValues = Array.from(picker.options).map((o) => o.value);
    expect(optionValues).not.toContain("tray-1");
    expect(optionValues).toContain("tray-2");

    fireEvent.change(screen.getByLabelText(/seeds sown for st-0001/i), { target: { value: "200" } });
    await waitFor(() => expect(screen.getByText(/200 total/i)).toBeInTheDocument());
  });

  it("blocks Review when no tray is selected", async () => {
    stubFetch();
    render(withQueryClient(<SowingForm farmId="farm-1" onSubmit={vi.fn()} isSubmitting={false} />));
    await selectNurseryAndSeedLot();

    fireEvent.click(screen.getByRole("button", { name: "Review" }));
    await waitFor(() => expect(screen.getByText(/select at least one seed tray/i)).toBeInTheDocument());
    expect(screen.queryByText("Review before sowing")).not.toBeInTheDocument();
  });

  it("rejects zero seeds sown", async () => {
    stubFetch();
    render(withQueryClient(<SowingForm farmId="farm-1" onSubmit={vi.fn()} isSubmitting={false} />));
    await selectNurseryAndSeedLot();
    fireEvent.change(screen.getByLabelText(/add a seed tray/i), { target: { value: "tray-1" } });
    await waitFor(() => expect(screen.getByText("ST-0001")).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText(/seeds sown for st-0001/i), { target: { value: "0" } });

    fireEvent.click(screen.getByRole("button", { name: "Review" }));
    await waitFor(() => expect(screen.getByText(/must be at least 1/i)).toBeInTheDocument());
  });

  it("shows a review screen with no invented batch code, then submits on confirm", async () => {
    stubFetch();
    const onSubmit = vi.fn();
    render(withQueryClient(<SowingForm farmId="farm-1" onSubmit={onSubmit} isSubmitting={false} />));
    await selectNurseryAndSeedLot();
    fireEvent.change(screen.getByLabelText(/add a seed tray/i), { target: { value: "tray-1" } });
    await waitFor(() => expect(screen.getByText("ST-0001")).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText(/seeds sown for st-0001/i), { target: { value: "200" } });
    fireEvent.change(screen.getByLabelText(/^date$/i), { target: { value: "2026-08-14" } });
    fireEvent.change(screen.getByLabelText(/^time$/i), { target: { value: "09:00" } });

    fireEvent.click(screen.getByRole("button", { name: "Review" }));
    await waitFor(() => expect(screen.getByText("Review before sowing")).toBeInTheDocument());
    expect(screen.getByText("generated on save")).toBeInTheDocument();
    expect(screen.getByText("SEED-01")).toBeInTheDocument();
    expect(screen.getByText("RZ-MAM-2026-001")).toBeInTheDocument();
    expect(onSubmit).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Sow" }));
    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
    const payload = onSubmit.mock.calls[0][0];
    expect(payload.seed_lot_id).toBe("lot-1");
    expect(payload.seeding_station_id).toBe("station-1");
    expect(payload.seeding_machine_id).toBeNull();
    expect(payload.trays).toEqual([{ carrier_id: "tray-1", seeds_sown: 200 }]);
  });

  it("returns to configure via Back without submitting", async () => {
    stubFetch();
    const onSubmit = vi.fn();
    render(withQueryClient(<SowingForm farmId="farm-1" onSubmit={onSubmit} isSubmitting={false} />));
    await selectNurseryAndSeedLot();
    fireEvent.change(screen.getByLabelText(/add a seed tray/i), { target: { value: "tray-1" } });
    await waitFor(() => expect(screen.getByText("ST-0001")).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText(/seeds sown for st-0001/i), { target: { value: "200" } });

    fireEvent.click(screen.getByRole("button", { name: "Review" }));
    await waitFor(() => expect(screen.getByText("Review before sowing")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Back" }));
    expect(screen.getByText("Nursery / Seeding Station")).toBeInTheDocument();
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("shows a server error on the review step", async () => {
    stubFetch();
    render(
      withQueryClient(
        <SowingForm
          farmId="farm-1" onSubmit={vi.fn()} isSubmitting={false}
          serverError="Seed Tray ST-0001 is already assigned to an active Crop Batch."
        />,
      ),
    );
    await selectNurseryAndSeedLot();
    fireEvent.change(screen.getByLabelText(/add a seed tray/i), { target: { value: "tray-1" } });
    await waitFor(() => expect(screen.getByText("ST-0001")).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText(/seeds sown for st-0001/i), { target: { value: "200" } });
    fireEvent.click(screen.getByRole("button", { name: "Review" }));

    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(/already assigned/i));
  });

  it("reuses the same client_command_id on a retry after a server error (replay-safe)", async () => {
    stubFetch();
    const onSubmit = vi.fn();
    render(withQueryClient(<SowingForm farmId="farm-1" onSubmit={onSubmit} isSubmitting={false} />));
    await selectNurseryAndSeedLot();
    fireEvent.change(screen.getByLabelText(/add a seed tray/i), { target: { value: "tray-1" } });
    await waitFor(() => expect(screen.getByText("ST-0001")).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText(/seeds sown for st-0001/i), { target: { value: "200" } });
    fireEvent.click(screen.getByRole("button", { name: "Review" }));
    await waitFor(() => expect(screen.getByText("Review before sowing")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "Sow" }));
    fireEvent.click(screen.getByRole("button", { name: "Sow" }));
    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(2));
    const firstId = onSubmit.mock.calls[0][0].client_command_id;
    const secondId = onSubmit.mock.calls[1][0].client_command_id;
    expect(firstId).toBe(secondId);
  });

  it("never mentions Germination anywhere in the form", async () => {
    stubFetch();
    render(withQueryClient(<SowingForm farmId="farm-1" onSubmit={vi.fn()} isSubmitting={false} />));
    await waitFor(() => expect(screen.getByText("NUR-01")).toBeInTheDocument());
    expect(screen.queryByText(/germinat/i)).not.toBeInTheDocument();
  });
});
