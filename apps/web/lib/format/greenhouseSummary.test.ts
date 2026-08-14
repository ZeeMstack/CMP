import { describe, expect, it } from "vitest";

import type { GreenhouseOverviewItem } from "@/lib/api/client";

import { structureSummaryLine } from "@/lib/format/greenhouseSummary";

function nurseryItem(counts: Partial<GreenhouseOverviewItem["counts"]>): GreenhouseOverviewItem {
  return {
    greenhouse_id: "gh-1",
    code: "NUR-01",
    name: "Nursery",
    classification: "nursery",
    status: "partial",
    counts: {
      zones: 0, spans: 0, tables: 0, gutters: 0, bag_positions: 0,
      seeding_stations: 0, germination_chambers: 0,
      seedling_tables: 0, intersalads_tables: 0, intervines_tables: 0,
      trolleys: 0, trolley_levels: 0, trolley_slots: 0, seeding_machines: 0,
      ...counts,
    },
  };
}

describe("structureSummaryLine (Nursery)", () => {
  it("includes Seeding Station and Germination Chamber in the structural summary", () => {
    const line = structureSummaryLine(nurseryItem({ seeding_stations: 1, germination_chambers: 1 }));
    expect(line).toBe("Seeding Station · Germination Chamber");
  });

  it("never blends Trolley/Seeding Machine counts into the structural summary -- FARM-SETUP-001.2 section 9", () => {
    // A durable-relationship claim would be implied if these appeared
    // indistinguishably alongside Seedling/InterSalads/InterVines counts
    // with no qualifier -- they must always carry an explicit
    // "farm-level equipment" label, appended as its own clause.
    const line = structureSummaryLine(nurseryItem({ seedling_tables: 3, trolleys: 1, seeding_machines: 1 }));
    expect(line).toBe("3 Seedling Tables · 1 Trolley, 1 Seeding Machines registered (farm-level equipment)");
  });

  it("still surfaces Trolley/Seeding Machine (clearly labeled) even with zero physical Nursery structure", () => {
    const line = structureSummaryLine(nurseryItem({ trolleys: 1 }));
    expect(line).toBe("No structure configured yet · 1 Trolley registered (farm-level equipment)");
  });

  it("shows the honest empty message when nothing at all is configured", () => {
    const line = structureSummaryLine(nurseryItem({}));
    expect(line).toBe("No structure configured yet");
  });
});
