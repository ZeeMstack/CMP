import { describe, expect, it } from "vitest";

import { DEFAULT_FORM_VALUES, buildGreenhouseSetupPayload, greenhouseSetupFormSchema } from "@/lib/validation/farmSetup";

describe("buildGreenhouseSetupPayload", () => {
  it("expands Leafy form values into per-span table generators (Scenario A shape)", () => {
    const values = {
      ...DEFAULT_FORM_VALUES,
      code: "GH-L01",
      name: "Leafy",
      classification: "leafy_greens" as const,
      leafy: {
        zoneCount: 2, zoneCodePrefix: "Z", spansPerZone: 2, spanCodePrefix: "S",
        tablesPerSpan: 3, tableCodePrefix: "T", tableCapacity: 24,
      },
    };
    const payload = buildGreenhouseSetupPayload(values, "cmd-1");

    expect(payload.classification).toBe("leafy_greens");
    expect(payload.client_command_id).toBe("cmd-1");
    expect(payload.leafy!.zones).toHaveLength(2);
    expect(payload.leafy!.zones[0].code).toBe("Z01");
    expect(payload.leafy!.zones[1].code).toBe("Z02");
    expect(payload.leafy!.zones[0].spans).toHaveLength(2);
    expect(payload.leafy!.zones[0].spans[0].code).toBe("S01");
    expect(payload.leafy!.zones[0].spans[0].tables).toEqual({
      code_prefix: "T", start: 1, end: 3, pad_width: 2, capacity: 24,
    });
    // Every span's own table generator restarts at 1 -- no artificial
    // cross-span numbering for Leafy tables.
    expect(payload.leafy!.zones[1].spans[1].tables!.start).toBe(1);
    expect(payload.vines).toBeUndefined();
    expect(payload.nursery).toBeUndefined();
  });

  it("expands Vines form values into gutter + bag-position generators (Scenario B shape)", () => {
    const values = {
      ...DEFAULT_FORM_VALUES,
      code: "GH-V01",
      name: "Vines",
      classification: "vines" as const,
      vines: {
        zoneCount: 1, zoneCodePrefix: "Z", spansPerZone: 2, spanCodePrefix: "S",
        guttersPerSpan: 2, gutterCodePrefix: "G", continueGutterNumbering: false,
        bagPositionsPerGutter: 5, bagPositionCodePrefix: "BP",
      },
    };
    const payload = buildGreenhouseSetupPayload(values, "cmd-2");

    expect(payload.vines!.zones).toHaveLength(1);
    expect(payload.vines!.zones[0].spans).toHaveLength(2);
    const [span1, span2] = payload.vines!.zones[0].spans;
    expect(span1.gutters).toEqual({
      code_prefix: "G", start: 1, end: 2, pad_width: 2,
      bag_positions_per_gutter: 5, bag_position_code_prefix: "BP", bag_position_pad_width: 3,
    });
    // Default (off): every span restarts gutter numbering at 1.
    expect(span2.gutters!.start).toBe(1);
    expect(span2.gutters!.end).toBe(2);
  });

  it("continues gutter numbering across spans when the option is enabled", () => {
    const values = {
      ...DEFAULT_FORM_VALUES,
      code: "GH-V02",
      name: "Vines",
      classification: "vines" as const,
      vines: {
        zoneCount: 1, zoneCodePrefix: "Z", spansPerZone: 2, spanCodePrefix: "S",
        guttersPerSpan: 8, gutterCodePrefix: "G", continueGutterNumbering: true,
        bagPositionsPerGutter: 1, bagPositionCodePrefix: "BP",
      },
    };
    const payload = buildGreenhouseSetupPayload(values, "cmd-3");
    const [span1, span2] = payload.vines!.zones[0].spans;
    // Matches the ticket's own example: Span 1 gutters 01-08, Span 2 gutters 09-16.
    expect(span1.gutters).toMatchObject({ start: 1, end: 8 });
    expect(span2.gutters).toMatchObject({ start: 9, end: 16 });
  });

  it("expands Nursery form values, omitting unselected groups (Scenario C shape)", () => {
    const values = {
      ...DEFAULT_FORM_VALUES,
      code: "NUR-01",
      name: "Nursery",
      classification: "nursery" as const,
      nursery: {
        includeSeedingStation: false, seedingStation: { code: "", name: "" },
        includeGerminationChamber: false,
        includeSeedling: true, seedlingTableCount: 3, seedlingCapacity: 30,
        includeIntersalads: true, intersaladsTableCount: 2, intersaladsCapacity: 24,
        includeIntervines: true, intervinesTableCount: 2, intervinesCapacity: 50,
        trolleyGenerator: { trolleyCount: 10, trolleyPrefix: "GT", levelsPerTrolley: 8, levelPrefix: "L", traysPerLevel: 5 },
        includeSeedingMachine: false, seedingMachine: { code: "" },
      },
    };
    const payload = buildGreenhouseSetupPayload(values, "cmd-4");

    expect(payload.nursery!.seedling_tables).toEqual({ code_prefix: "ST", start: 1, end: 3, pad_width: 2, capacity: 30 });
    expect(payload.nursery!.intersalads_tables).toEqual({ code_prefix: "IS", start: 1, end: 2, pad_width: 2, capacity: 24 });
    expect(payload.nursery!.intervines_tables).toEqual({ code_prefix: "IV", start: 1, end: 2, pad_width: 2, capacity: 50 });
    expect(payload.nursery!.seeding_station).toBeNull();
    expect(payload.nursery!.germination_chamber).toBeNull();
    expect(payload.nursery!.trolley_generator).toBeNull();
    expect(payload.nursery!.seeding_machines).toEqual([]);
    // No Zone/Span anywhere in a Nursery payload.
    expect(payload.leafy).toBeUndefined();
    expect(payload.vines).toBeUndefined();
  });

  it("includes seeding station, germination chamber, and its Trolley generator when the chamber is selected", () => {
    const values = {
      ...DEFAULT_FORM_VALUES,
      code: "NUR-03",
      name: "Nursery",
      classification: "nursery" as const,
      nursery: {
        includeSeedingStation: true, seedingStation: { code: "SEED-01", name: "" },
        includeGerminationChamber: true,
        includeSeedling: false, seedlingTableCount: 1, seedlingCapacity: 1,
        includeIntersalads: false, intersaladsTableCount: 1, intersaladsCapacity: 1,
        includeIntervines: false, intervinesTableCount: 1, intervinesCapacity: 1,
        trolleyGenerator: { trolleyCount: 3, trolleyPrefix: "GT", levelsPerTrolley: 8, levelPrefix: "L", traysPerLevel: 20 },
        includeSeedingMachine: true, seedingMachine: { code: "SM-01" },
      },
    };
    const payload = buildGreenhouseSetupPayload(values, "cmd-6");

    expect(payload.nursery!.seeding_station).toEqual({ code: "SEED-01", name: null });
    // PILOT-UX-001B2 final correction: no operator-facing Chamber Code/Name
    // -- GrowCMP always sends the frozen default identity.
    expect(payload.nursery!.germination_chamber).toEqual({ code: "GERM-01", name: null });
    // PILOT-UX-001B2 final correction: no separate Trolley toggle -- the
    // generator is always sent alongside an included Germination Chamber.
    expect(payload.nursery!.trolley_generator).toEqual({
      trolley_count: 3, trolley_prefix: "GT", trolley_pad_width: 2,
      levels: { level_count: 8, trays_per_level: 20, level_pad_width: 2, level_prefix: "L" },
    });
    expect(payload.nursery!.seeding_machines).toEqual([{ code: "SM-01", name: null }]);
  });

  it("omits the Trolley generator when the Germination Chamber is not selected", () => {
    const values = {
      ...DEFAULT_FORM_VALUES,
      code: "NUR-02",
      name: "Nursery",
      classification: "nursery" as const,
      nursery: {
        includeSeedingStation: false, seedingStation: { code: "", name: "" },
        includeGerminationChamber: false,
        includeSeedling: false, seedlingTableCount: 1, seedlingCapacity: 1,
        includeIntersalads: false, intersaladsTableCount: 1, intersaladsCapacity: 1,
        includeIntervines: false, intervinesTableCount: 1, intervinesCapacity: 1,
        trolleyGenerator: { trolleyCount: 3, trolleyPrefix: "GT", levelsPerTrolley: 8, levelPrefix: "L", traysPerLevel: 20 },
        includeSeedingMachine: true, seedingMachine: { code: "SM-01" },
      },
    };
    const payload = buildGreenhouseSetupPayload(values, "cmd-5");

    expect(payload.nursery!.trolley_generator).toBeNull();
    expect(payload.nursery!.seeding_machines).toEqual([{ code: "SM-01", name: null }]);
  });
});

describe("greenhouseSetupFormSchema", () => {
  it("rejects a zero table capacity", () => {
    const values = { ...DEFAULT_FORM_VALUES, code: "GH", name: "GH", leafy: { ...DEFAULT_FORM_VALUES.leafy, tableCapacity: 0 } };
    const result = greenhouseSetupFormSchema.safeParse(values);
    expect(result.success).toBe(false);
  });

  it("rejects a negative capacity", () => {
    const values = { ...DEFAULT_FORM_VALUES, code: "GH", name: "GH", leafy: { ...DEFAULT_FORM_VALUES.leafy, tableCapacity: -1 } };
    const result = greenhouseSetupFormSchema.safeParse(values);
    expect(result.success).toBe(false);
  });

  it("rejects a blank code", () => {
    const values = { ...DEFAULT_FORM_VALUES, code: "  ", name: "GH" };
    const result = greenhouseSetupFormSchema.safeParse(values);
    expect(result.success).toBe(false);
  });

  it("rejects a Nursery configuration with every section unselected", () => {
    const values = {
      ...DEFAULT_FORM_VALUES, code: "NUR", name: "Nursery", classification: "nursery" as const,
      nursery: {
        includeSeedingStation: false, seedingStation: { code: "", name: "" },
        includeGerminationChamber: false,
        includeSeedling: false, seedlingTableCount: 1, seedlingCapacity: 1,
        includeIntersalads: false, intersaladsTableCount: 1, intersaladsCapacity: 1,
        includeIntervines: false, intervinesTableCount: 1, intervinesCapacity: 1,
        trolleyGenerator: { trolleyCount: 10, trolleyPrefix: "GT", levelsPerTrolley: 8, levelPrefix: "L", traysPerLevel: 5 },
        includeSeedingMachine: false, seedingMachine: { code: "" },
      },
    };
    const result = greenhouseSetupFormSchema.safeParse(values);
    expect(result.success).toBe(false);
  });

  it("requires a seeding station code only when the seeding station is actually selected", () => {
    const baseNursery = { ...DEFAULT_FORM_VALUES.nursery, includeSeedingStation: true, seedingStation: { code: "", name: "" } };
    const rejected = greenhouseSetupFormSchema.safeParse({
      ...DEFAULT_FORM_VALUES, code: "NUR", name: "Nursery", classification: "nursery" as const, nursery: baseNursery,
    });
    expect(rejected.success).toBe(false);

    const accepted = greenhouseSetupFormSchema.safeParse({
      ...DEFAULT_FORM_VALUES, code: "NUR", name: "Nursery", classification: "nursery" as const,
      nursery: { ...baseNursery, seedingStation: { code: "SEED-01", name: "" } },
    });
    expect(accepted.success).toBe(true);
  });

  it("accepts a Germination Chamber selection with no Code/Name fields (operator only toggles inclusion)", () => {
    const accepted = greenhouseSetupFormSchema.safeParse({
      ...DEFAULT_FORM_VALUES, code: "NUR", name: "Nursery", classification: "nursery" as const,
      nursery: { ...DEFAULT_FORM_VALUES.nursery, includeGerminationChamber: true },
    });
    expect(accepted.success).toBe(true);
  });

  it("accepts a valid Leafy configuration", () => {
    const values = { ...DEFAULT_FORM_VALUES, code: "GH-L01", name: "Leafy GH" };
    const result = greenhouseSetupFormSchema.safeParse(values);
    expect(result.success).toBe(true);
  });

  it("rejects a blank Trolley prefix (the generator fields are always live, no enable/disable toggle)", () => {
    const baseNursery = {
      ...DEFAULT_FORM_VALUES.nursery,
      trolleyGenerator: { ...DEFAULT_FORM_VALUES.nursery.trolleyGenerator, trolleyPrefix: "" },
    };
    const rejected = greenhouseSetupFormSchema.safeParse({
      ...DEFAULT_FORM_VALUES, code: "NUR", name: "Nursery", classification: "nursery" as const, nursery: baseNursery,
    });
    expect(rejected.success).toBe(false);
  });

  it("accepts the default Germination Trolleys generator values", () => {
    const accepted = greenhouseSetupFormSchema.safeParse({
      ...DEFAULT_FORM_VALUES, code: "NUR", name: "Nursery", classification: "nursery" as const,
      nursery: { ...DEFAULT_FORM_VALUES.nursery, includeGerminationChamber: true },
    });
    expect(accepted.success).toBe(true);
  });
});
