import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { GreenhouseOverviewItem } from "@/lib/api/client";

import { GreenhouseOverviewCard } from "./GreenhouseOverviewCard";

function item(overrides: Partial<GreenhouseOverviewItem> = {}): GreenhouseOverviewItem {
  return {
    greenhouse_id: "gh-1",
    code: "GH-01",
    name: "Greenhouse 1",
    classification: "leafy_greens",
    status: "configured",
    counts: {
      zones: 2, spans: 4, tables: 12, gutters: 0, bag_positions: 0,
      seeding_stations: 0, germination_chambers: 0,
      seedling_tables: 0, intersalads_tables: 0, intervines_tables: 0,
      trolleys: 0, trolley_levels: 0, trolley_slots: 0, seeding_machines: 0,
    },
    ...overrides,
  };
}

describe("GreenhouseOverviewCard", () => {
  it("shows code, classification, status, and derived structure counts -- never fabricated", () => {
    render(<GreenhouseOverviewCard item={item()} farmId="farm-1" />);
    expect(screen.getByText("GH-01")).toBeInTheDocument();
    expect(screen.getByText("Leafy Greens")).toBeInTheDocument();
    expect(screen.getByText("Configured")).toBeInTheDocument();
    expect(screen.getByText("2 Zones · 4 Spans · 12 Tables")).toBeInTheDocument();
  });

  it("shows an honest empty-structure message rather than a misleading count for an unconfigured greenhouse", () => {
    render(
      <GreenhouseOverviewCard
        item={item({
          status: "empty",
          counts: {
            zones: 0, spans: 0, tables: 0, gutters: 0, bag_positions: 0,
            seeding_stations: 0, germination_chambers: 0,
            seedling_tables: 0, intersalads_tables: 0, intervines_tables: 0,
            trolleys: 0, trolley_levels: 0, trolley_slots: 0, seeding_machines: 0,
          },
        })}
        farmId="farm-1"
      />,
    );
    expect(screen.getByText("Empty")).toBeInTheDocument();
    expect(screen.getByText("No structure configured yet")).toBeInTheDocument();
  });

  it("summarizes a Vines greenhouse using Gutters/Bag Positions, never Tables", () => {
    render(
      <GreenhouseOverviewCard
        item={item({
          classification: "vines",
          counts: {
            zones: 2, spans: 11, tables: 0, gutters: 88, bag_positions: 1760,
            seeding_stations: 0, germination_chambers: 0,
            seedling_tables: 0, intersalads_tables: 0, intervines_tables: 0,
            trolleys: 0, trolley_levels: 0, trolley_slots: 0, seeding_machines: 0,
          },
        })}
        farmId="farm-1"
      />,
    );
    expect(screen.getByText("2 Zones · 11 Spans · 88 Gutters · 1,760 Bag Positions")).toBeInTheDocument();
  });

  it("links to the greenhouse's structure detail page", () => {
    render(<GreenhouseOverviewCard item={item()} farmId="farm-1" />);
    expect(screen.getByRole("link")).toHaveAttribute("href", "/farms/farm-1/farm-setup/gh-1");
  });

  it("renders a Nursery greenhouse as a non-overlapping label/value structure list, not a packed metrics row", () => {
    render(
      <GreenhouseOverviewCard
        item={item({
          classification: "nursery",
          counts: {
            zones: 0, spans: 0, tables: 0, gutters: 0, bag_positions: 0,
            seeding_stations: 1, germination_chambers: 1,
            seedling_tables: 50, intersalads_tables: 72, intervines_tables: 26,
            trolleys: 0, trolley_levels: 0, trolley_slots: 0, seeding_machines: 0,
          },
        })}
        farmId="farm-1"
      />,
    );
    expect(screen.getByText("Seeding")).toBeInTheDocument();
    expect(screen.getByText("Germination")).toBeInTheDocument();
    expect(screen.getAllByText("Configured").length).toBeGreaterThanOrEqual(2);
    expect(screen.getByText("50 tables")).toBeInTheDocument();
    expect(screen.getByText("72 tables")).toBeInTheDocument();
    expect(screen.getByText("26 tables")).toBeInTheDocument();
  });

  it("shows 'Not configured' for an unconfigured Nursery dimension, never a fabricated count", () => {
    render(
      <GreenhouseOverviewCard
        item={item({
          classification: "nursery",
          status: "empty",
          counts: {
            zones: 0, spans: 0, tables: 0, gutters: 0, bag_positions: 0,
            seeding_stations: 0, germination_chambers: 0,
            seedling_tables: 0, intersalads_tables: 0, intervines_tables: 0,
            trolleys: 0, trolley_levels: 0, trolley_slots: 0, seeding_machines: 0,
          },
        })}
        farmId="farm-1"
      />,
    );
    expect(screen.getAllByText("Not configured").length).toBe(5);
  });
});
