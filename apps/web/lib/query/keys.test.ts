import { describe, expect, it } from "vitest";

import { queryKeys } from "@/lib/query/keys";

const TENANT_A = "11111111-1111-1111-1111-111111111111";
const TENANT_B = "22222222-2222-2222-2222-222222222222";
const FARM_ID = "farm-shared-id";
const BATCH_ID = "batch-shared-id";
const LOCATION_ID = "location-shared-id";

/** The load-bearing property (AUTH-001B2): every tenant-scoped key must
 * differ across tenants EVEN WHEN every other identifier (farm/batch/
 * location id) is identical -- this is what makes cross-tenant cache
 * leakage structurally impossible rather than merely unlikely because
 * UUIDs don't collide in practice. */
describe("tenant-scoped query keys differ across tenants for identical sub-ids", () => {
  it("farms()", () => {
    expect(queryKeys.farms(TENANT_A)).not.toEqual(queryKeys.farms(TENANT_B));
  });

  it("farm() with the same farmId", () => {
    expect(queryKeys.farm(TENANT_A, FARM_ID)).not.toEqual(queryKeys.farm(TENANT_B, FARM_ID));
  });

  it("locationsTree() with the same farmId", () => {
    expect(queryKeys.locationsTree(TENANT_A, FARM_ID)).not.toEqual(queryKeys.locationsTree(TENANT_B, FARM_ID));
  });

  it("locationSubtreeOccupancy() with the same farmId/locationId", () => {
    expect(queryKeys.locationSubtreeOccupancy(TENANT_A, FARM_ID, LOCATION_ID)).not.toEqual(
      queryKeys.locationSubtreeOccupancy(TENANT_B, FARM_ID, LOCATION_ID),
    );
  });

  it("cropBatch() with the same farmId/batchId", () => {
    expect(queryKeys.cropBatch(TENANT_A, FARM_ID, BATCH_ID)).not.toEqual(
      queryKeys.cropBatch(TENANT_B, FARM_ID, BATCH_ID),
    );
  });

  it("stageHistory() with the same farmId/batchId", () => {
    expect(queryKeys.stageHistory(TENANT_A, FARM_ID, BATCH_ID)).not.toEqual(
      queryKeys.stageHistory(TENANT_B, FARM_ID, BATCH_ID),
    );
  });

  it("batchLineage() with the same farmId/batchId", () => {
    expect(queryKeys.batchLineage(TENANT_A, FARM_ID, BATCH_ID)).not.toEqual(
      queryKeys.batchLineage(TENANT_B, FARM_ID, BATCH_ID),
    );
  });

  it("qualityHolds() with the same farmId/batchId", () => {
    expect(queryKeys.qualityHolds(TENANT_A, FARM_ID, BATCH_ID)).not.toEqual(
      queryKeys.qualityHolds(TENANT_B, FARM_ID, BATCH_ID),
    );
  });

  it("operationalSummary() with the same farmId/state", () => {
    expect(queryKeys.operationalSummary(TENANT_A, FARM_ID, "active")).not.toEqual(
      queryKeys.operationalSummary(TENANT_B, FARM_ID, "active"),
    );
  });

  it("batchOperationalContext() with the same farmId/batchId", () => {
    expect(queryKeys.batchOperationalContext(TENANT_A, FARM_ID, BATCH_ID)).not.toEqual(
      queryKeys.batchOperationalContext(TENANT_B, FARM_ID, BATCH_ID),
    );
  });
});

describe("tenant id is an explicit, inspectable segment (not just key inequality by accident)", () => {
  it("farms() key literally contains the tenant id", () => {
    expect(queryKeys.farms(TENANT_A)).toContain(TENANT_A);
  });

  it("cropBatch() key literally contains the tenant id", () => {
    expect(queryKeys.cropBatch(TENANT_A, FARM_ID, BATCH_ID)).toContain(TENANT_A);
  });
});

describe("authBootstrap key is deliberately NOT tenant-scoped", () => {
  it("is a fixed key with no parameters", () => {
    expect(queryKeys.authBootstrap()).toEqual(["auth", "bootstrap"]);
  });

  it("does not accept or embed a tenant id", () => {
    const key = queryKeys.authBootstrap();
    expect(key).not.toContain(TENANT_A);
    expect(key).not.toContain(TENANT_B);
  });
});

describe("same tenant, different sub-ids still produce distinct keys (no regression from the tenant-prefix change)", () => {
  it("two different farms under the same tenant", () => {
    expect(queryKeys.farm(TENANT_A, "farm-1")).not.toEqual(queryKeys.farm(TENANT_A, "farm-2"));
  });

  it("operational-summary active vs all under the same tenant/farm", () => {
    expect(queryKeys.operationalSummary(TENANT_A, FARM_ID, "active")).not.toEqual(
      queryKeys.operationalSummary(TENANT_A, FARM_ID, "all"),
    );
  });
});
