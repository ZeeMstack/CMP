import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { setTestSearch } from "@/components/water/waterTestNavigation";
import { withQueryClient } from "@/lib/test-utils";

vi.mock("next/navigation", async () =>
  (await import("@/components/water/waterTestNavigation")).createNavigationMock("/farms/farm-1/water/exposure"),
);

import WaterExposurePage, { validateWindow } from "./page";

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const BASE_INTERVAL = {
  batch_id: "batch-1", carrier_id: "car-1", location_id: "loc-t1", reservoir_id: "res-1", irrigation_circuit_id: "ic-1",
  water_delivery_point_id: "dp-1", delivery_point_location_id: "loc-z1", water_delivery_event_id: null,
  batch_carrier_assignment_id: "bca-1", occupancy_id: "occ-1", reservoir_circuit_link_id: "rcl-1",
  circuit_delivery_point_link_id: "cdl-1", start_clipped_to_window: false, end_clipped_to_window: false, open_ended_sources: [],
};

// Two Delivery Points serving ONE Location over the same span, plus a
// touching recorded interval, plus one open (clipped) interval.
const INTERVALS = [
  { ...BASE_INTERVAL, exposure_kind: "CONFIGURED_TOPOLOGY_EXPOSURE", interval_start: "2026-09-01T00:00:00Z", interval_end: "2026-09-01T06:00:00Z" },
  { ...BASE_INTERVAL, exposure_kind: "CONFIGURED_TOPOLOGY_EXPOSURE", interval_start: "2026-09-01T00:00:00Z", interval_end: "2026-09-01T06:00:00Z", water_delivery_point_id: "dp-2", circuit_delivery_point_link_id: "cdl-2" },
  { ...BASE_INTERVAL, exposure_kind: "RECORDED_DELIVERY_EXPOSURE", interval_start: "2026-09-01T06:00:00Z", interval_end: "2026-09-01T08:00:00Z", water_delivery_event_id: "del-1" },
  { ...BASE_INTERVAL, exposure_kind: "CONFIGURED_TOPOLOGY_EXPOSURE", interval_start: "2026-09-01T08:00:00Z", interval_end: "2026-09-02T00:00:00Z", end_clipped_to_window: true, open_ended_sources: ["OCCUPANCY", "RESERVOIR_CIRCUIT_LINK"] },
];
const GAP = {
  reason: "NO_COMPLETE_TOPOLOGY_ROUTE", gap_start: "2026-08-31T20:00:00Z", gap_end: "2026-09-01T00:00:00Z", batch_id: "batch-1",
  carrier_id: "car-1", location_id: "loc-t1", batch_carrier_assignment_id: "bca-1", occupancy_id: "occ-1",
  start_clipped_to_window: true, end_clipped_to_window: false, open_ended_sources: [],
};

function stubFetch() {
  const gets: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      gets.push(url);
      if (url.includes("/crop-batches/batch-1/water-exposure-timeline")) {
        return json({ batch_id: "batch-1", farm_id: "farm-1", window_start: "2026-08-31T20:00:00Z", window_end: "2026-09-02T00:00:00Z", interval_convention: "HALF_OPEN_START_INCLUSIVE_END_EXCLUSIVE", intervals: INTERVALS, gaps: [GAP] });
      }
      if (url.includes("/reservoirs/res-1/water-exposure-timeline")) {
        return json({ anchor_type: "reservoir", anchor_id: "res-1", farm_id: "farm-1", window_start: "2026-08-31T20:00:00Z", window_end: "2026-09-02T00:00:00Z", interval_convention: "HALF_OPEN_START_INCLUSIVE_END_EXCLUSIVE", intervals: [] });
      }
      if (url.includes("operational-summary")) return json([{ id: "batch-1", code: "LET-001" }]);
      if (url.includes("/carriers")) return json([{ id: "car-1", code: "PP-001" }]);
      if (url.includes("/locations/tree")) {
        return json([{ id: "loc-gh", code: "GH1", name: "GH", children: [{ id: "loc-z1", code: "Z1", name: "Z", children: [{ id: "loc-t1", code: "T01", name: "T", children: [] }] }] }]);
      }
      if (url.includes("/water-delivery-points")) return json([{ id: "dp-1", code: "DP-1", name: "Zone emitter A" }, { id: "dp-2", code: "DP-2", name: "Zone emitter B" }]);
      if (url.includes("/irrigation-circuits")) return json([{ id: "ic-1", code: "IC-1", name: "Drip" }]);
      if (url.includes("/reservoirs")) return json([{ id: "res-1", code: "RES-1", name: "Tank A" }]);
      return json([]);
    }),
  );
  return gets;
}

async function query(entityLabel: string, entity: string) {
  await waitFor(() => expect(screen.getByRole("option", { name: entity })).toBeInTheDocument());
  const select = screen.getByLabelText(entityLabel);
  fireEvent.change(select, { target: { value: (screen.getByRole("option", { name: entity }) as HTMLOptionElement).value } });
  fireEvent.change(screen.getByLabelText("Window start (included)"), { target: { value: "2026-09-01T00:00" } });
  fireEvent.change(screen.getByLabelText("Window end (excluded)"), { target: { value: "2026-09-02T04:00" } });
  fireEvent.click(screen.getByRole("button", { name: "Show exposure" }));
}

const FORBIDDEN = /affected|contaminat|infect|disease|confirmed exposure/i;

beforeEach(() => setTestSearch(""));
afterEach(() => vi.unstubAllGlobals());

describe("validateWindow", () => {
  it("requires both ends and start strictly before end", () => {
    expect(validateWindow("", "2026-09-02T00:00")).toBeNull();
    expect(validateWindow("2026-09-02T00:00", "2026-09-02T00:00")).toEqual({ error: expect.stringMatching(/before/) });
    expect(validateWindow("2026-09-01T00:00", "2026-09-02T00:00")).toMatchObject({ start: expect.stringMatching(/Z$/) });
  });
});

describe("Exposure workspace on D0 timelines (UX-OPS-001D)", () => {
  it("By Batch: uses the timeline endpoint and renders every interval row unmerged, half-open copy, gaps, and open-source clipping", async () => {
    const gets = stubFetch();
    render(withQueryClient(<WaterExposurePage />));
    await query("Batch", "LET-001");

    const rows = await screen.findAllByTestId("exposure-interval-row");
    expect(rows).toHaveLength(4); // duplicate-provenance + touching rows never merged
    expect(rows[0]).toHaveTextContent("RES-1 → IC-1 → DP-1");
    expect(rows[1]).toHaveTextContent("RES-1 → IC-1 → DP-2");
    expect(rows[2]).toHaveTextContent("Recorded Delivery Exposure");
    expect(rows[0]).toHaveTextContent("Configured Topology Exposure");
    expect(rows[0]).toHaveTextContent("LET-001 · PP-001 · GH1 / Z1 / T01");
    expect(rows[3]).toHaveTextContent(/clipped at window end \(still open: Carrier occupancy, Reservoir → Circuit link\)/);

    const summary = screen.getByTestId("window-summary");
    expect(summary).toHaveTextContent(/start time is included and its end time is excluded/);
    expect(summary).toHaveTextContent(/still open: Carrier occupancy, Reservoir → Circuit link\. The window end is not a recorded end/);

    const gap = screen.getByTestId("exposure-gap-row");
    expect(gap).toHaveTextContent("No complete topology route");
    expect(gap).toHaveTextContent("starts at window start");

    const timelineCall = gets.find((g) => g.includes("/water-exposure-timeline"));
    expect(timelineCall).toContain("/crop-batches/batch-1/water-exposure-timeline?farm_id=farm-1&window_start=");
    expect(gets.some((g) => g.includes("/water-exposure?") || g.includes("exposed-placements"))).toBe(false);

    // Full ids only in the selected provenance surface.
    expect(screen.queryByText(/rcl-1/)).not.toBeInTheDocument();
    fireEvent.click(within(rows[1]).getByRole("button"));
    expect(await screen.findByText("RES-1 — Tank A → IC-1 — Drip → DP-2 — Zone emitter B")).toBeInTheDocument();
    fireEvent.click(within(rows[2]).getByRole("button"));
    expect(await screen.findByText("rcl-1")).toBeInTheDocument();
    expect(screen.getByText("del-1")).toBeInTheDocument();

    expect(document.body.textContent).not.toMatch(FORBIDDEN);
  });

  it("By Reservoir: an empty result is 'no matching interval evidence', and says reverse views return no gap rows", async () => {
    setTestSearch("view=reservoir");
    const gets = stubFetch();
    render(withQueryClient(<WaterExposurePage />));
    await query("Reservoir / Tank", "RES-1 — Tank A");
    await screen.findByText("No matching interval evidence in this window");
    expect(screen.getByText(/does not return Batch gap rows/)).toBeInTheDocument();
    expect(gets.some((g) => g.includes("/reservoirs/res-1/water-exposure-timeline?farm_id=farm-1"))).toBe(true);
    expect(document.body.textContent).not.toMatch(FORBIDDEN);
  });

  it("never queries an invalid window", async () => {
    const gets = stubFetch();
    render(withQueryClient(<WaterExposurePage />));
    await waitFor(() => expect(screen.getByRole("option", { name: "LET-001" })).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText("Batch"), { target: { value: "batch-1" } });
    fireEvent.change(screen.getByLabelText("Window start (included)"), { target: { value: "2026-09-02T00:00" } });
    fireEvent.change(screen.getByLabelText("Window end (excluded)"), { target: { value: "2026-09-01T00:00" } });
    fireEvent.click(screen.getByRole("button", { name: "Show exposure" }));
    expect(screen.getByRole("alert")).toHaveTextContent("The window start must be before the window end.");
    expect(gets.some((g) => g.includes("water-exposure-timeline"))).toBe(false);
  });
});
