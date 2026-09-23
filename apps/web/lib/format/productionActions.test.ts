import { describe, expect, it } from "vitest";

import { leafyPlateActions, vinesGroupActions, vinesGrowBagActions } from "./productionActions";

const plate = {
  batch_id: "b1",
  batch_carrier_assignment_id: "a1",
  current_living_population: 40,
  current_location: { id: "loc" },
};

describe("leafyPlateActions", () => {
  it("offers loss (primary), move, observation, inspection, and reprint for a living, located Plate", () => {
    const actions = leafyPlateActions("f1", plate);
    expect(actions.map((a) => a.kind)).toEqual([
      "record_loss", "move", "record_observation", "inspect_crop", "reprint_label",
    ]);
  });

  it("never offers Move when the server reports no current location", () => {
    const kinds = leafyPlateActions("f1", { ...plate, current_location: null }).map((a) => a.kind);
    expect(kinds).not.toContain("move");
    expect(kinds).toContain("record_loss");
  });

  it("offers only Reprint once living population is zero", () => {
    const kinds = leafyPlateActions("f1", { ...plate, current_living_population: 0 }).map((a) => a.kind);
    expect(kinds).toEqual(["reprint_label"]);
  });

  it("preserves the exact placement on Inspect Crop and Observation links", () => {
    const actions = leafyPlateActions("f1", plate);
    expect(actions.find((a) => a.kind === "inspect_crop")?.href).toBe(
      "/farms/f1/production/inspect?batchId=b1&assignmentId=a1",
    );
    expect(actions.find((a) => a.kind === "record_observation")?.href).toBe(
      "/farms/f1/observations?batchId=b1&assignmentId=a1",
    );
  });
});

describe("vines actions", () => {
  it("never offers Move for a Grow Bag (no Vines relocation command exists)", () => {
    const kinds = vinesGrowBagActions("f1", "b1", { batch_carrier_assignment_id: "a1", living_plant_count: 3 }).map((a) => a.kind);
    expect(kinds).not.toContain("move");
    expect(kinds[0]).toBe("record_loss");
  });

  it("offers no loss for an exhausted Grow Bag", () => {
    const kinds = vinesGrowBagActions("f1", "b1", { batch_carrier_assignment_id: "a1", living_plant_count: 0 }).map((a) => a.kind);
    expect(kinds).toEqual(["reprint_label"]);
  });

  it("keeps a (Batch, Gutter) group at Batch level, never narrowed to one placement", () => {
    const actions = vinesGroupActions("f1", "b1", 12);
    expect(actions.find((a) => a.kind === "inspect_crop")?.href).toBe("/farms/f1/production/inspect?batchId=b1");
    expect(vinesGroupActions("f1", "b1", 0)).toEqual([]);
  });
});
