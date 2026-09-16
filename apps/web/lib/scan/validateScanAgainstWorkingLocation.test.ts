import { describe, expect, it } from "vitest";

import type { ScanContext } from "@/lib/api/client";

import { filterActionsForLocationValidation, validateScanAgainstWorkingLocation } from "./validateScanAgainstWorkingLocation";
import type { WorkingLocation } from "./workingLocation";

function workingLocation(overrides: Partial<WorkingLocation> = {}): WorkingLocation {
  return {
    locationId: "table-07",
    farmId: "farm-1",
    code: "T07",
    pathString: "GH-01 / Zone 2 / Span 4 / Table 07",
    selectedAt: "2026-01-01T00:00:00Z",
    expiresAt: "2026-01-01T12:00:00Z",
    ...overrides,
  };
}

function locationPath(ids: string[], pathString: string) {
  return { path_string: pathString, codes: ids, ids };
}

const base = { qr_identifier_id: "qr-1", farm_id: "farm-1", code: "CODE-1", actions: [], work_items: [] };

function assignmentContext(overrides: Partial<Extract<ScanContext, { entity_type: "batch_carrier_assignment" }>> = {}) {
  return {
    ...base,
    entity_type: "batch_carrier_assignment" as const,
    batch: { id: "batch-1", code: "B-001", crop: { code: "ICE", common_name: "Iceberg" }, variety: null },
    carrier_code: "PP-01",
    current_location: locationPath(["gh-01", "zone-2", "span-4", "table-07"], "GH-01 / Zone 2 / Span 4 / Table 07"),
    released: false,
    unresolved_reason: null,
    ...overrides,
  };
}

function carrierContext(overrides: Partial<Extract<ScanContext, { entity_type: "carrier" }>> = {}) {
  return {
    ...base,
    entity_type: "carrier" as const,
    carrier_type_name: "Production Cultivation Plate",
    status: "active",
    current_batch: null,
    current_location: locationPath(["gh-01", "zone-2", "span-4", "table-07"], "GH-01 / Zone 2 / Span 4 / Table 07"),
    unresolved_reason: null,
    ...overrides,
  };
}

function locationContext(overrides: Partial<Extract<ScanContext, { entity_type: "location" }>> = {}) {
  return {
    ...base,
    entity_type: "location" as const,
    name: "Table 08",
    location: locationPath(["gh-01", "zone-2", "span-4", "table-08"], "GH-01 / Zone 2 / Span 4 / Table 08"),
    occupants: [],
    ...overrides,
  };
}

function cropBatchContext(overrides: Partial<Extract<ScanContext, { entity_type: "crop_batch" }>> = {}) {
  return {
    ...base,
    entity_type: "crop_batch" as const,
    crop: { code: "ICE", common_name: "Iceberg" },
    variety: null,
    state: "active",
    current_stage_name: "Growing",
    placements: [],
    ...overrides,
  };
}

function assetContext(overrides: Partial<Extract<ScanContext, { entity_type: "asset" }>> = {}) {
  return {
    ...base,
    entity_type: "asset" as const,
    name: "Trolley 1",
    asset_type_name: "Germination Trolley",
    status: "active",
    current_location: null,
    unresolved_reason: "occupant has no active occupancy",
    ...overrides,
  };
}

describe("validateScanAgainstWorkingLocation", () => {
  it("NO_WORKING_LOCATION when no working location is active", () => {
    expect(validateScanAgainstWorkingLocation(null, carrierContext())).toEqual({ kind: "NO_WORKING_LOCATION" });
  });

  it("MATCH_EXACT: scanned placement's current location equals the working location", () => {
    const result = validateScanAgainstWorkingLocation(workingLocation({ locationId: "table-07" }), assignmentContext());
    expect(result.kind).toBe("MATCH_EXACT");
  });

  it("MATCH_DESCENDANT: working location is an ancestor of the scanned resource's current location", () => {
    const result = validateScanAgainstWorkingLocation(
      workingLocation({ locationId: "gh-01" }),
      assignmentContext({ current_location: locationPath(["gh-01", "zone-2", "span-4", "table-07"], "GH-01 / Zone 2 / Span 4 / Table 07") }),
    );
    expect(result.kind).toBe("MATCH_DESCENDANT");
  });

  it("MISMATCH: a different branch/table", () => {
    const result = validateScanAgainstWorkingLocation(
      workingLocation({ locationId: "table-07" }),
      assignmentContext({ current_location: locationPath(["gh-01", "zone-2", "span-5", "table-02"], "GH-01 / Zone 2 / Span 5 / Table 02") }),
    );
    expect(result).toMatchObject({ kind: "MISMATCH", reason: "different_location" });
  });

  it("MISMATCH: the reverse case -- the resource's own recorded location is an ancestor of the working location -- is never treated as an exact match", () => {
    // Working location = Table 07 (deep); scanned entity's own current
    // location is only known at the coarser GH-01 level.
    const result = validateScanAgainstWorkingLocation(
      workingLocation({ locationId: "table-07" }),
      carrierContext({ current_location: locationPath(["gh-01"], "GH-01") }),
    );
    expect(result.kind).not.toBe("MATCH_EXACT");
    expect(result.kind).not.toBe("MATCH_DESCENDANT");
    expect(result.kind).toBe("MISMATCH");
  });

  it("MISMATCH: different farm, even if location ids happened to coincide", () => {
    const result = validateScanAgainstWorkingLocation(
      workingLocation({ locationId: "table-07", farmId: "farm-A" }),
      assignmentContext({ farm_id: "farm-B", current_location: locationPath(["table-07"], "Table 07") }),
    );
    expect(result).toMatchObject({ kind: "MISMATCH", reason: "different_farm" });
  });

  it("HISTORICAL: a released placement is never a current MATCH, even if its former location matches the working location", () => {
    const result = validateScanAgainstWorkingLocation(
      workingLocation({ locationId: "table-01" }),
      assignmentContext({ released: true, current_location: locationPath(["table-01"], "Table 01") }),
    );
    expect(result.kind).toBe("HISTORICAL");
  });

  it("CANNOT_VALIDATE: a split/multi-placement Batch is never an arbitrary MATCH", () => {
    const result = validateScanAgainstWorkingLocation(
      workingLocation({ locationId: "table-07" }),
      cropBatchContext({
        placements: [
          { batch_carrier_assignment_id: "a1", carrier_code: "C1", location: locationPath(["table-07"], "Table 07") },
          { batch_carrier_assignment_id: "a2", carrier_code: "C2", location: locationPath(["table-08"], "Table 08") },
        ],
      }),
    );
    expect(result.kind).toBe("CANNOT_VALIDATE");
  });

  it("CANNOT_VALIDATE: a single-placement Batch scan still never proves exact physical placement", () => {
    const result = validateScanAgainstWorkingLocation(
      workingLocation({ locationId: "table-07" }),
      cropBatchContext({
        placements: [{ batch_carrier_assignment_id: "a1", carrier_code: "C1", location: locationPath(["table-07"], "Table 07") }],
      }),
    );
    expect(result.kind).toBe("CANNOT_VALIDATE");
  });

  it("MATCH_EXACT: Carrier reused Batch A -> Batch B validates against the Carrier's own CURRENT (Batch B) location, never a historical one", () => {
    // The Carrier's own current_location already reflects its current
    // occupancy (Batch B) regardless of which Batch previously occupied
    // it -- qr_service resolves this fresh, independent of Batch identity.
    const result = validateScanAgainstWorkingLocation(
      workingLocation({ locationId: "table-09" }),
      carrierContext({
        current_batch: { id: "batch-B", code: "B-002", crop: { code: "ICE", common_name: "Iceberg" }, variety: null },
        current_location: locationPath(["table-09"], "Table 09"),
      }),
    );
    expect(result.kind).toBe("MATCH_EXACT");
  });

  it("CANNOT_VALIDATE: a resource with no authoritative location, rather than a guessed match", () => {
    const result = validateScanAgainstWorkingLocation(workingLocation(), assetContext());
    expect(result.kind).toBe("CANNOT_VALIDATE");
  });

  it("CANNOT_VALIDATE: Harvested/Graded/Finished Goods lots have no modeled location", () => {
    const harvestedLot = validateScanAgainstWorkingLocation(workingLocation(), {
      ...base,
      entity_type: "harvested_produce_lot" as const,
      batch: { id: "batch-1", code: "B-001", crop: { code: "ICE", common_name: "Iceberg" }, variety: null },
      total_harvested_weight_kg: "10",
      total_whole_unit_count: null,
      effective_time: "2026-01-01T00:00:00Z",
    });
    expect(harvestedLot.kind).toBe("CANNOT_VALIDATE");
  });

  it("Location scan: same Location as the working location -> MATCH_EXACT", () => {
    const result = validateScanAgainstWorkingLocation(
      workingLocation({ locationId: "table-08" }),
      locationContext({ location: locationPath(["gh-01", "zone-2", "span-4", "table-08"], "GH-01 / Zone 2 / Span 4 / Table 08") }),
    );
    expect(result.kind).toBe("MATCH_EXACT");
  });

  it("Location scan: a child Location under the working parent -> MATCH_DESCENDANT", () => {
    const result = validateScanAgainstWorkingLocation(
      workingLocation({ locationId: "gh-01" }),
      locationContext({ location: locationPath(["gh-01", "zone-2"], "GH-01 / Zone 2") }),
    );
    expect(result.kind).toBe("MATCH_DESCENDANT");
  });

  it("Location scan: a sibling Location -> MISMATCH", () => {
    const result = validateScanAgainstWorkingLocation(
      workingLocation({ locationId: "table-07" }),
      locationContext({ location: locationPath(["gh-01", "zone-2", "span-4", "table-08"], "GH-01 / Zone 2 / Span 4 / Table 08") }),
    );
    expect(result).toMatchObject({ kind: "MISMATCH", reason: "different_location" });
  });
});

describe("filterActionsForLocationValidation", () => {
  const actions = [
    { label: "View Batch", href: "/a" },
    { label: "Harvest", href: "/b" },
    { label: "Record Observation", href: "/c" },
    { label: "View traceability", href: "/d" },
  ];

  it("withholds physical-operation actions under MISMATCH", () => {
    const filtered = filterActionsForLocationValidation(actions, { kind: "MISMATCH", reason: "different_location", pathString: "x" });
    expect(filtered.map((a) => a.label)).toEqual(["View Batch", "View traceability"]);
  });

  it("never withholds any action under MATCH", () => {
    const filtered = filterActionsForLocationValidation(actions, { kind: "MATCH_EXACT", pathString: "x" });
    expect(filtered).toHaveLength(actions.length);
  });

  // PILOT-AGRO-001B Part 10: MISMATCH must never present Inspect Crop as
  // location-validated.
  it("withholds Inspect Crop under MISMATCH", () => {
    const withInspect = [...actions, { label: "Inspect Crop", href: "/e" }];
    const filtered = filterActionsForLocationValidation(withInspect, { kind: "MISMATCH", reason: "different_location", pathString: "x" });
    expect(filtered.map((a) => a.label)).not.toContain("Inspect Crop");
  });

  it("never withholds any action under CANNOT_VALIDATE -- the destination page's own validation still applies", () => {
    const filtered = filterActionsForLocationValidation(actions, { kind: "CANNOT_VALIDATE", reason: "x" });
    expect(filtered).toHaveLength(actions.length);
  });

  it("never withholds any action when there is no working location", () => {
    const filtered = filterActionsForLocationValidation(actions, { kind: "NO_WORKING_LOCATION" });
    expect(filtered).toHaveLength(actions.length);
  });
});
