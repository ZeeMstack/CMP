import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { GreenhouseStructureRead } from "@/lib/api/client";

import { GreenhouseStructureView } from "./GreenhouseStructureView";

describe("GreenhouseStructureView", () => {
  it("renders Leafy structure with table capacities, collapsed below the Zone level by default", () => {
    const structure: GreenhouseStructureRead = {
      greenhouse_id: "gh-1", code: "GH-L01", name: "Leafy", classification: "leafy_greens",
      leafy_zones: [
        {
          id: "z1", code: "Z01",
          spans: [
            { id: "s1", code: "S01", tables: [{ id: "t1", code: "T01", capacity: 24 }, { id: "t2", code: "T02", capacity: 24 }] },
          ],
        },
      ],
    };
    render(<GreenhouseStructureView structure={structure} />);

    expect(screen.getByText("Zone Z01")).toBeInTheDocument();
    // Spans start collapsed -- table detail not shown until expanded.
    expect(screen.queryByText(/capacity 24/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByText(/Span S01/));
    expect(screen.getAllByText(/capacity 24/).length).toBe(2);
  });

  it("renders Vines structure with gutters and bag-position counts -- no Gutter Side node anywhere", () => {
    const structure: GreenhouseStructureRead = {
      greenhouse_id: "gh-2", code: "GH-V01", name: "Vines", classification: "vines",
      vines_zones: [
        { id: "z1", code: "Z01", spans: [{ id: "s1", code: "S01", gutters: [{ id: "g1", code: "G01", bag_position_count: 5 }] }] },
      ],
    };
    render(<GreenhouseStructureView structure={structure} />);
    fireEvent.click(screen.getByText(/Span S01/));
    expect(screen.getByText("Gutter G01 · 5 bag positions")).toBeInTheDocument();
    expect(screen.queryByText(/gutter side/i)).not.toBeInTheDocument();
  });

  it("renders Nursery structure grouped by Seedling/InterSalads/InterVines -- no Zone/Span", () => {
    const structure: GreenhouseStructureRead = {
      greenhouse_id: "gh-3", code: "NUR-01", name: "Nursery", classification: "nursery",
      nursery_seedling: { area_id: "area-1", tables: [{ id: "t1", code: "ST01", capacity: 30 }] },
      nursery_intersalads: { area_id: null, tables: [] },
      nursery_intervines: { area_id: null, tables: [] },
    };
    render(<GreenhouseStructureView structure={structure} />);
    expect(screen.getByText("Seedling · 1 tables")).toBeInTheDocument();
    expect(screen.queryByText(/zone/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/span/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/InterSalads/)).not.toBeInTheDocument();
  });

  it("renders Nursery Seeding Station and Germination Chamber when present", () => {
    const structure: GreenhouseStructureRead = {
      greenhouse_id: "gh-4", code: "NUR-02", name: "Nursery", classification: "nursery",
      nursery_seeding_station: { id: "sec-1", code: "SEED-01", name: "Seeding Station" },
      nursery_germination_chamber: { id: "sec-2", code: "GERM-01", name: "Germination Chamber" },
      nursery_seedling: { area_id: null, tables: [] },
      nursery_intersalads: { area_id: null, tables: [] },
      nursery_intervines: { area_id: null, tables: [] },
    };
    render(<GreenhouseStructureView structure={structure} />);
    expect(screen.getByText("Seeding Station · SEED-01")).toBeInTheDocument();
    expect(screen.getByText("Germination Chamber · GERM-01")).toBeInTheDocument();
  });
});
