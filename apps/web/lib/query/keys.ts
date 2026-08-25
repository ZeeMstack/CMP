/** Query key factory (AUTH-001B2: every tenant-scoped key is prefixed
 * with the active tenant id, so cached data from one tenant can never be
 * returned for a `useQuery` call made under a different tenant -- this is
 * a structural property of the key space, not an accident of farm/batch/
 * location UUIDs happening not to collide across tenants. `authBootstrap`
 * is the one deliberate exception: it is genuinely tenant-independent
 * (it's what *tells* the app which tenants exist), so it is never
 * tenant-prefixed and must never be cleared by anything except an
 * explicit auth-state change. */
export const queryKeys = {
  authBootstrap: () => ["auth", "bootstrap"] as const,

  farms: (tenantId: string) => ["tenant", tenantId, "farms"] as const,
  farm: (tenantId: string, farmId: string) => ["tenant", tenantId, "farms", farmId] as const,
  locationsTree: (tenantId: string, farmId: string) =>
    ["tenant", tenantId, "farms", farmId, "locations", "tree"] as const,
  locationSubtreeOccupancy: (tenantId: string, farmId: string, locationId: string) =>
    ["tenant", tenantId, "farms", farmId, "locations", locationId, "subtree-occupancy"] as const,
  cropBatch: (tenantId: string, farmId: string, batchId: string) =>
    ["tenant", tenantId, "farms", farmId, "crop-batches", batchId] as const,
  stageHistory: (tenantId: string, farmId: string, batchId: string) =>
    ["tenant", tenantId, "farms", farmId, "crop-batches", batchId, "stage-history"] as const,
  batchLineage: (tenantId: string, farmId: string, batchId: string) =>
    ["tenant", tenantId, "farms", farmId, "crop-batches", batchId, "lineage"] as const,
  qualityHolds: (tenantId: string, farmId: string, batchId: string) =>
    ["tenant", tenantId, "farms", farmId, "crop-batches", batchId, "quality-holds"] as const,
  // `state` is part of the key so `active` and `all` never collide in cache.
  operationalSummary: (tenantId: string, farmId: string, state: "active" | "all") =>
    ["tenant", tenantId, "farms", farmId, "crop-batches", "operational-summary", state] as const,
  batchOperationalContext: (tenantId: string, farmId: string, batchId: string) =>
    ["tenant", tenantId, "farms", farmId, "crop-batches", batchId, "operational-context"] as const,
  greenhouseSetupOverview: (tenantId: string, farmId: string) =>
    ["tenant", tenantId, "farms", farmId, "farm-setup", "greenhouses"] as const,
  greenhouseStructure: (tenantId: string, farmId: string, greenhouseId: string) =>
    ["tenant", tenantId, "farms", farmId, "farm-setup", "greenhouses", greenhouseId] as const,

  // --- NURSERY-OPS-001 -----------------------------------------------------
  crops: (tenantId: string) => ["tenant", tenantId, "crops"] as const,
  varieties: (tenantId: string, cropId: string) => ["tenant", tenantId, "crops", cropId, "varieties"] as const,
  seedLots: (tenantId: string, farmId: string) => ["tenant", tenantId, "farms", farmId, "seed-lots"] as const,
  seedLot: (tenantId: string, farmId: string, seedLotId: string) =>
    ["tenant", tenantId, "farms", farmId, "seed-lots", seedLotId] as const,
  availableSeedTrays: (tenantId: string, farmId: string) =>
    ["tenant", tenantId, "farms", farmId, "nursery", "seed-trays", "available"] as const,
  sowings: (tenantId: string, farmId: string, batchId: string) =>
    ["tenant", tenantId, "farms", farmId, "crop-batches", batchId, "sowings"] as const,
  seedLotBatches: (tenantId: string, farmId: string, seedLotId: string) =>
    ["tenant", tenantId, "farms", farmId, "seed-lots", seedLotId, "crop-batches"] as const,
  assets: (tenantId: string, farmId: string, assetType: string) =>
    ["tenant", tenantId, "farms", farmId, "assets", assetType] as const,

  // --- NURSERY-OPS-002A -----------------------------------------------------
  availableChambers: (tenantId: string, farmId: string) =>
    ["tenant", tenantId, "farms", farmId, "germination", "chambers", "available"] as const,
  availableTrolleys: (tenantId: string, farmId: string) =>
    ["tenant", tenantId, "farms", farmId, "germination", "trolleys", "available"] as const,
  trolleySlots: (tenantId: string, farmId: string, trolleyId: string) =>
    ["tenant", tenantId, "farms", farmId, "germination", "trolleys", trolleyId, "slots"] as const,
  germinationTrays: (tenantId: string, farmId: string) =>
    ["tenant", tenantId, "farms", farmId, "germination", "trays"] as const,

  // --- NURSERY-OPS-002B -----------------------------------------------------
  currentGerminationOutcomes: (tenantId: string, farmId: string, batchId: string) =>
    ["tenant", tenantId, "farms", farmId, "crop-batches", batchId, "germination-outcomes", "current"] as const,

  // --- NURSERY-OPS-003A -----------------------------------------------------
  seedlingCandidateTrays: (tenantId: string, farmId: string) =>
    ["tenant", tenantId, "farms", farmId, "nursery", "seedling", "trays"] as const,
  availableSeedlingTables: (tenantId: string, farmId: string) =>
    ["tenant", tenantId, "farms", farmId, "nursery", "seedling", "tables", "available"] as const,

  // --- NURSERY-OPS-003B -----------------------------------------------------
  seedlingDispositionReasons: (tenantId: string, farmId: string) =>
    ["tenant", tenantId, "farms", farmId, "nursery", "seedling", "disposition-reasons"] as const,
  seedlingBiologicalTrays: (tenantId: string, farmId: string) =>
    ["tenant", tenantId, "farms", farmId, "nursery", "seedling", "biological-trays"] as const,
  seedlingDispositionHistory: (tenantId: string, farmId: string, seedlingEntryId: string) =>
    ["tenant", tenantId, "farms", farmId, "nursery", "seedling", "dispositions", seedlingEntryId] as const,

  // --- CARRIER-CONFIG-001 ----------------------------------------------------
  // Tenant-scoped, never farm-scoped -- one CarrierSpecification is reusable
  // across every farm this tenant has.
  carrierTypes: (tenantId: string) => ["tenant", tenantId, "carrier-types"] as const,
  carrierSpecifications: (tenantId: string) => ["tenant", tenantId, "carrier-specifications"] as const,
  carrierSpecification: (tenantId: string, specificationId: string) =>
    ["tenant", tenantId, "carrier-specifications", specificationId] as const,

  // --- NURSERY-OPS-004B.2 -----------------------------------------------------
  availableIntersaladsPlates: (tenantId: string, farmId: string) =>
    ["tenant", tenantId, "farms", farmId, "nursery", "intersalads", "available-plates"] as const,
  locationOccupants: (tenantId: string, farmId: string, locationId: string) =>
    ["tenant", tenantId, "farms", farmId, "locations", locationId, "occupants"] as const,

  // --- NURSERY-OPS-005B -----------------------------------------------------
  // `batchId` is part of the key (default "" before a Batch is established)
  // so the unfiltered and Batch-filtered source lists never collide in cache.
  availableLeafyProductionSources: (tenantId: string, farmId: string, batchId: string) =>
    ["tenant", tenantId, "farms", farmId, "leafy-production", "available-sources", batchId] as const,
  availableProductionPlates: (tenantId: string, farmId: string) =>
    ["tenant", tenantId, "farms", farmId, "leafy-production", "available-plates"] as const,
  activeProductionPlates: (tenantId: string, farmId: string, batchId: string) =>
    ["tenant", tenantId, "farms", farmId, "leafy-production", "active-plates", batchId] as const,
  productionDispositionHistory: (tenantId: string, farmId: string, batchCarrierAssignmentId: string, batchId: string) =>
    ["tenant", tenantId, "farms", farmId, "leafy-production", "dispositions", batchCarrierAssignmentId, batchId] as const,

  // --- HARVEST-OPS-001 SLICE 2 -------------------------------------------------
  // `batchId` defaults to "" (unfiltered) so the unfiltered and Batch-filtered
  // variants never collide in cache, mirroring NURSERY-OPS-005B's own convention.
  harvestablePlates: (tenantId: string, farmId: string, batchId: string) =>
    ["tenant", tenantId, "farms", farmId, "leafy-production", "harvestable-plates", batchId] as const,
  leafyHarvests: (tenantId: string, farmId: string, batchId: string) =>
    ["tenant", tenantId, "farms", farmId, "leafy-production", "harvests", batchId] as const,
  leafyHarvest: (tenantId: string, farmId: string, harvestEventId: string) =>
    ["tenant", tenantId, "farms", farmId, "leafy-production", "harvests", "detail", harvestEventId] as const,
};
