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
const SPEC_200 = { id: "spec-1", code: "ST-SPEC-200", name: "200 Cell Tray", biological_position_count: 200 };
// Three 200-site trays -- enough to exercise an exact multiple (2 trays),
// a partial final tray (2 trays, one partial), and an insufficient-supply
// warning (asking for more than 3 trays' worth) without a 20-row fixture.
const AVAILABLE_TRAYS = [
  { id: "tray-1", code: "ST-0001", carrier_type: { id: "ct-1", code: "seed_tray", name: "Seed Tray" }, specification_id: "spec-1", specification: SPEC_200 },
  { id: "tray-2", code: "ST-0002", carrier_type: { id: "ct-1", code: "seed_tray", name: "Seed Tray" }, specification_id: "spec-1", specification: SPEC_200 },
  { id: "tray-3", code: "ST-0003", carrier_type: { id: "ct-1", code: "seed_tray", name: "Seed Tray" }, specification_id: "spec-1", specification: SPEC_200 },
  { id: "tray-legacy", code: "ST-9999", carrier_type: { id: "ct-1", code: "seed_tray", name: "Seed Tray" }, specification_id: null, specification: null },
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
  it("PILOT-BLOCKER-001: shows an actionable empty state linking to Physical Carriers when no trays exist", async () => {
    stubFetch({ trays: [] });
    render(withQueryClient(<SowingForm farmId="farm-1" onSubmit={vi.fn()} isSubmitting={false} />));
    await waitFor(() => expect(screen.getByText("NUR-01")).toBeInTheDocument());
    expect(screen.getByText("No physical Seed Trays are available for this farm.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /set up seed trays/i })).toHaveAttribute(
      "href",
      "/farms/farm-1/carriers",
    );
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

    const stationSelect = screen.getByLabelText(/^seeding station$/i) as HTMLSelectElement;
    expect(stationSelect.value).toBe("");
    fireEvent.change(screen.getByLabelText(/seed lot/i), { target: { value: "lot-1" } });
    fireEvent.click(screen.getByRole("button", { name: "Review" }));
    await waitFor(() => expect(screen.getByText(/seeding station is required/i)).toBeInTheDocument());

    fireEvent.change(stationSelect, { target: { value: "station-2" } });
    fireEvent.click(screen.getByRole("button", { name: /select trays manually instead/i }));
    fireEvent.change(screen.getByLabelText(/add a seed tray/i), { target: { value: "tray-1" } });
    await waitFor(() => expect(screen.getByText("ST-0001")).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText(/sown sites for st-0001/i), { target: { value: "150" } });
    fireEvent.change(screen.getByLabelText(/seeds sown for st-0001/i), { target: { value: "200" } });
    fireEvent.click(screen.getByRole("button", { name: "Review" }));
    await waitFor(() => expect(screen.getByText("Review before sowing")).toBeInTheDocument());
    expect(screen.getByText("SEED-02")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Sow" }));
    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
    expect(onSubmit.mock.calls[0][0].seeding_station_id).toBe("station-2");
  });

  it("returns to configure via Back without submitting, and retries reuse the same client_command_id", async () => {
    stubFetch();
    const onSubmit = vi.fn();
    render(
      withQueryClient(
        <SowingForm
          farmId="farm-1" onSubmit={onSubmit} isSubmitting={false}
          serverError="Seed Tray ST-0001 is already assigned to an active Crop Batch."
        />,
      ),
    );
    await selectNurseryAndSeedLot();
    fireEvent.click(screen.getByRole("button", { name: /select trays manually instead/i }));
    fireEvent.change(screen.getByLabelText(/add a seed tray/i), { target: { value: "tray-1" } });
    await waitFor(() => expect(screen.getByText("ST-0001")).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText(/sown sites for st-0001/i), { target: { value: "150" } });
    fireEvent.change(screen.getByLabelText(/seeds sown for st-0001/i), { target: { value: "200" } });

    fireEvent.click(screen.getByRole("button", { name: "Review" }));
    await waitFor(() => expect(screen.getByText("Review before sowing")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Back" }));
    expect(screen.getByText("Nursery / Seeding Station")).toBeInTheDocument();
    expect(onSubmit).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Review" }));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(/already assigned/i));
    fireEvent.click(screen.getByRole("button", { name: "Sow" }));
    fireEvent.click(screen.getByRole("button", { name: "Sow" }));
    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(2));
    expect(onSubmit.mock.calls[0][0].client_command_id).toBe(onSubmit.mock.calls[1][0].client_command_id);
  });

  it("prevents submitting a sown site count above a manually-selected tray's known capacity", async () => {
    stubFetch();
    const onSubmit = vi.fn();
    render(withQueryClient(<SowingForm farmId="farm-1" onSubmit={onSubmit} isSubmitting={false} />));
    await selectNurseryAndSeedLot();
    fireEvent.click(screen.getByRole("button", { name: /select trays manually instead/i }));
    fireEvent.change(screen.getByLabelText(/add a seed tray/i), { target: { value: "tray-1" } });
    await waitFor(() => expect(screen.getByText("ST-0001")).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText(/sown sites for st-0001/i), { target: { value: "201" } });
    fireEvent.change(screen.getByLabelText(/seeds sown for st-0001/i), { target: { value: "201" } });

    fireEvent.click(screen.getByRole("button", { name: "Review" }));
    await waitFor(() => expect(screen.getByText(/exceeds this tray's known capacity/i)).toBeInTheDocument());
    expect(onSubmit).not.toHaveBeenCalled();
  });

  // --- PILOT-UX-001 (CTO correction): fast-path tray auto-allocation --------
  // Sites and seeds are separate, explicit inputs. Tray count and per-tray
  // sown_site_count derive ONLY from Sites to sow / tray capacity; seeds are
  // never assumed equal to sites.

  it("keeps the simple single-button fast path when Seeds to sow equals Sites to sow, with no distribution prompt", async () => {
    stubFetch();
    const onSubmit = vi.fn();
    render(withQueryClient(<SowingForm farmId="farm-1" onSubmit={onSubmit} isSubmitting={false} />));
    await selectNurseryAndSeedLot();

    fireEvent.change(screen.getByLabelText(/^sites to sow$/i), { target: { value: "250" } });
    fireEvent.change(screen.getByLabelText(/^seeds to sow$/i), { target: { value: "250" } });
    fireEvent.change(screen.getByLabelText(/tray specification/i), { target: { value: "spec-1" } });
    await waitFor(() => expect(screen.getByRole("button", { name: /auto-allocate 2 trays/i })).toBeInTheDocument());
    // Equal totals are unambiguous -- no distribution choice is offered.
    expect(screen.queryByRole("button", { name: /distribute proportionally/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Customize" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /auto-allocate 2 trays/i }));

    fireEvent.click(screen.getByRole("button", { name: "Review" }));
    await waitFor(() => expect(screen.getByText("Review before sowing")).toBeInTheDocument());
    // No fabricated "distribution" claim for the unambiguous equal case.
    expect(screen.queryByText(/seed distribution/i)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Sow" }));

    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
    expect(onSubmit.mock.calls[0][0].trays).toEqual([
      { carrier_id: "tray-1", sown_site_count: 200, seeds_sown: 200 },
      { carrier_id: "tray-2", sown_site_count: 50, seeds_sown: 50 },
    ]);
  });

  it("never silently fabricates a tray-level seed distribution when Seeds to sow exceeds Sites to sow -- requires an explicit choice", async () => {
    stubFetch();
    const onSubmit = vi.fn();
    render(withQueryClient(<SowingForm farmId="farm-1" onSubmit={onSubmit} isSubmitting={false} />));
    await selectNurseryAndSeedLot();

    fireEvent.change(screen.getByLabelText(/^sites to sow$/i), { target: { value: "400" } });
    fireEvent.change(screen.getByLabelText(/^seeds to sow$/i), { target: { value: "1000" } });
    fireEvent.change(screen.getByLabelText(/tray specification/i), { target: { value: "spec-1" } });
    await waitFor(() => expect(screen.getByText(/required trays:/i)).toBeInTheDocument());
    expect(screen.getByText("2")).toBeInTheDocument();

    // No single "Auto-allocate" button, and no trays created, until the
    // operator makes an explicit distribution choice.
    expect(screen.queryByRole("button", { name: /^auto-allocate/i })).not.toBeInTheDocument();
    expect(screen.queryByText("2 Seed Trays")).not.toBeInTheDocument();
    const distributeButton = screen.getByRole("button", { name: /distribute proportionally/i });
    const customizeButton = screen.getByRole("button", { name: "Customize" });
    expect(distributeButton).toBeInTheDocument();
    expect(customizeButton).toBeInTheDocument();

    // "Customize" is the explicit manual alternative: sites are allocated,
    // seeds are left for the operator to enter themselves -- never guessed.
    fireEvent.click(customizeButton);
    await waitFor(() => expect(screen.getByText("ST-0001")).toBeInTheDocument());
    expect((screen.getByLabelText(/sown sites for st-0001/i) as HTMLInputElement).value).toBe("200");
    expect((screen.getByLabelText(/seeds sown for st-0001/i) as HTMLInputElement).value).toBe("0");
    fireEvent.click(screen.getByRole("button", { name: "Review" }));
    // Blocked by the tray schema's existing validation (unset seeds fail
    // either "at least 1" or "must be >= sown sites") -- exact wording isn't
    // the point here, only that an unset seed count can never reach Review.
    await waitFor(() => expect(screen.queryByText("Review before sowing")).not.toBeInTheDocument());
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("distributes an explicit 'Distribute proportionally' choice deterministically, reconciling to the exact seed total", async () => {
    stubFetch();
    const onSubmit = vi.fn();
    render(withQueryClient(<SowingForm farmId="farm-1" onSubmit={onSubmit} isSubmitting={false} />));
    await selectNurseryAndSeedLot();

    // 3 equal 200-site trays, 1000 seeds: 1000/3 per tray is not a whole
    // number (333.33...) -- the remainder must reconcile deterministically
    // (largest-remainder method) to sum exactly to 1000, not float-drift.
    fireEvent.change(screen.getByLabelText(/^sites to sow$/i), { target: { value: "600" } });
    fireEvent.change(screen.getByLabelText(/^seeds to sow$/i), { target: { value: "1000" } });
    fireEvent.change(screen.getByLabelText(/tray specification/i), { target: { value: "spec-1" } });
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /distribute proportionally/i })).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByRole("button", { name: /distribute proportionally/i }));

    await waitFor(() => expect(screen.getByText("3 Seed Trays")).toBeInTheDocument());
    expect(screen.getByText(/distributed proportionally to sown sites/i)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Review" }));
    await waitFor(() => expect(screen.getByText("Review before sowing")).toBeInTheDocument());
    // The review must show that proportional distribution was selected.
    expect(screen.getByText(/distributed proportionally to sown sites/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Sow" }));

    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
    const trays = onSubmit.mock.calls[0][0].trays;
    expect(trays.reduce((sum: number, t: { sown_site_count: number }) => sum + t.sown_site_count, 0)).toBe(600);
    expect(trays.reduce((sum: number, t: { seeds_sown: number }) => sum + t.seeds_sown, 0)).toBe(1000);
    expect(trays).toEqual([
      { carrier_id: "tray-1", sown_site_count: 200, seeds_sown: 334 },
      { carrier_id: "tray-2", sown_site_count: 200, seeds_sown: 333 },
      { carrier_id: "tray-3", sown_site_count: 200, seeds_sown: 333 },
    ]);
  });

  it("blocks auto-allocate and shows an error when Seeds to sow is less than Sites to sow, without touching tray count", async () => {
    stubFetch();
    render(withQueryClient(<SowingForm farmId="farm-1" onSubmit={vi.fn()} isSubmitting={false} />));
    await selectNurseryAndSeedLot();

    fireEvent.change(screen.getByLabelText(/^sites to sow$/i), { target: { value: "400" } });
    fireEvent.change(screen.getByLabelText(/^seeds to sow$/i), { target: { value: "300" } });
    fireEvent.change(screen.getByLabelText(/tray specification/i), { target: { value: "spec-1" } });

    await waitFor(() => expect(screen.getByText(/must be at least the number of sites/i)).toBeInTheDocument());
    // Tray count still reflects sites/capacity, unaffected by the invalid seed value.
    expect(screen.getByText("2")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /auto-allocate 2 trays/i })).toBeDisabled();
  });

  it("blocks auto-allocate and points to Physical Carriers when not enough trays of that specification are registered", async () => {
    stubFetch();
    render(withQueryClient(<SowingForm farmId="farm-1" onSubmit={vi.fn()} isSubmitting={false} />));
    await selectNurseryAndSeedLot();

    // 3 trays available, but 800 sites at 200/tray needs 4.
    fireEvent.change(screen.getByLabelText(/^sites to sow$/i), { target: { value: "800" } });
    fireEvent.change(screen.getByLabelText(/^seeds to sow$/i), { target: { value: "800" } });
    fireEvent.change(screen.getByLabelText(/tray specification/i), { target: { value: "spec-1" } });

    await waitFor(() => expect(screen.getByText(/only 3 of the 4 needed seed trays/i)).toBeInTheDocument());
    expect(screen.getByRole("link", { name: /register more seed trays/i })).toHaveAttribute(
      "href",
      "/farms/farm-1/carriers",
    );
    expect(screen.getByRole("button", { name: /auto-allocate 4 trays/i })).toBeDisabled();
  });

  it("lets an operator customize an auto-allocated tray's counts on demand, without losing the other trays", async () => {
    stubFetch();
    const onSubmit = vi.fn();
    render(withQueryClient(<SowingForm farmId="farm-1" onSubmit={onSubmit} isSubmitting={false} />));
    await selectNurseryAndSeedLot();

    fireEvent.change(screen.getByLabelText(/^sites to sow$/i), { target: { value: "400" } });
    fireEvent.change(screen.getByLabelText(/^seeds to sow$/i), { target: { value: "400" } });
    fireEvent.change(screen.getByLabelText(/tray specification/i), { target: { value: "spec-1" } });
    await waitFor(() => expect(screen.getByRole("button", { name: /auto-allocate 2 trays/i })).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /auto-allocate 2 trays/i }));
    await waitFor(() => expect(screen.getByText("2 Seed Trays")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: /customize allocation/i }));
    await waitFor(() => expect(screen.getByText("ST-0001")).toBeInTheDocument());
    expect(screen.getByText("ST-0002")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText(/seeds sown for st-0001/i), { target: { value: "250" } });

    fireEvent.click(screen.getByRole("button", { name: "Review" }));
    await waitFor(() => expect(screen.getByText("Review before sowing")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Sow" }));

    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
    expect(onSubmit.mock.calls[0][0].trays).toEqual([
      { carrier_id: "tray-1", sown_site_count: 200, seeds_sown: 250 },
      { carrier_id: "tray-2", sown_site_count: 200, seeds_sown: 200 },
    ]);
  });

  it("keeps manual tray selection available for legacy trays with no known specification", async () => {
    stubFetch();
    const onSubmit = vi.fn();
    render(withQueryClient(<SowingForm farmId="farm-1" onSubmit={onSubmit} isSubmitting={false} />));
    await selectNurseryAndSeedLot();

    // A legacy tray has no specification, so it never appears in the fast
    // path's tray-specification list -- only manual selection can use it.
    expect(screen.queryByText(/ST-9999/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /select trays manually instead/i }));

    fireEvent.change(screen.getByLabelText(/add a seed tray/i), { target: { value: "tray-legacy" } });
    await waitFor(() => expect(screen.getByText("ST-9999")).toBeInTheDocument());
    expect(screen.getByText("Capacity unknown")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText(/sown sites for st-9999/i), { target: { value: "150" } });
    fireEvent.change(screen.getByLabelText(/seeds sown for st-9999/i), { target: { value: "150" } });
    fireEvent.click(screen.getByRole("button", { name: "Review" }));
    await waitFor(() => expect(screen.getByText("Review before sowing")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Sow" }));

    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
    expect(onSubmit.mock.calls[0][0].trays).toEqual([{ carrier_id: "tray-legacy", sown_site_count: 150, seeds_sown: 150 }]);
  });

  it("never mentions Germination anywhere in the form", async () => {
    stubFetch();
    render(withQueryClient(<SowingForm farmId="farm-1" onSubmit={vi.fn()} isSubmitting={false} />));
    await waitFor(() => expect(screen.getByText("NUR-01")).toBeInTheDocument());
    expect(screen.queryByText(/germinat/i)).not.toBeInTheDocument();
  });

  describe("planPrefill (PLANNING-OPS-001)", () => {
    function stubFetchWithCrop() {
      vi.stubGlobal(
        "fetch",
        vi.fn(async (input: RequestInfo | URL) => {
          const url = String(input);
          if (url.includes("/farm-setup/greenhouses/gh-1")) return jsonResponse(NURSERY_STRUCTURE);
          if (url.includes("/farm-setup/greenhouses")) return jsonResponse(NURSERY_OVERVIEW);
          if (url.includes("/crops/crop-1/varieties")) return jsonResponse([{ id: "var-1", code: "PANG", name: "Pangkor" }]);
          if (url.includes("/crops")) return jsonResponse([{ id: "crop-1", code: "ICE", common_name: "Iceberg Lettuce" }]);
          if (url.includes("/seed-lots")) return jsonResponse(SEED_LOTS);
          if (url.includes("/nursery/seed-trays/available")) return jsonResponse(AVAILABLE_TRAYS);
          if (url.includes("/assets")) return jsonResponse([]);
          return jsonResponse([]);
        }),
      );
    }

    it("carries seeding_program_line_id through to the submitted Sowing payload, never a second Sowing form", async () => {
      stubFetchWithCrop();
      const onSubmit = vi.fn();
      render(
        withQueryClient(
          <SowingForm
            farmId="farm-1" onSubmit={onSubmit} isSubmitting={false}
            planPrefill={{ seedingProgramLineId: "line-1", cropId: "crop-1", varietyId: "var-1" }}
          />,
        ),
      );
      await waitFor(() => expect(screen.getByText(/fulfilling a seeding program plan line/i)).toBeInTheDocument());
      expect(screen.getAllByLabelText(/^seed lot$/i)).toHaveLength(1);

      await selectNurseryAndSeedLot();
      fireEvent.change(screen.getByLabelText(/^sites to sow$/i), { target: { value: "200" } });
      fireEvent.change(screen.getByLabelText(/^seeds to sow$/i), { target: { value: "200" } });
      fireEvent.change(screen.getByLabelText(/tray specification/i), { target: { value: "spec-1" } });
      await waitFor(() => expect(screen.getByRole("button", { name: /auto-allocate 1 tray$/i })).toBeInTheDocument());
      fireEvent.click(screen.getByRole("button", { name: /auto-allocate 1 tray$/i }));
      fireEvent.click(screen.getByRole("button", { name: "Review" }));
      await waitFor(() => expect(screen.getByText("Review before sowing")).toBeInTheDocument());
      fireEvent.click(screen.getByRole("button", { name: "Sow" }));

      await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
      expect(onSubmit.mock.calls[0][0].seeding_program_line_id).toBe("line-1");
    });
  });
});
