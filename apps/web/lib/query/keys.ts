/** Farm-scoped query key factory -- keeps every hook's key shape consistent
 * and gives future mutation tickets a clear, farm-scoped prefix to
 * invalidate against. */
export const queryKeys = {
  farms: () => ["farms"] as const,
  farm: (farmId: string) => ["farms", farmId] as const,
  locationsTree: (farmId: string) => ["farms", farmId, "locations", "tree"] as const,
  locationOccupant: (farmId: string, locationId: string) =>
    ["farms", farmId, "locations", locationId, "occupant"] as const,
  cropBatches: (farmId: string) => ["farms", farmId, "crop-batches"] as const,
  cropBatch: (farmId: string, batchId: string) => ["farms", farmId, "crop-batches", batchId] as const,
  stageHistory: (farmId: string, batchId: string) =>
    ["farms", farmId, "crop-batches", batchId, "stage-history"] as const,
  batchLineage: (farmId: string, batchId: string) =>
    ["farms", farmId, "crop-batches", batchId, "lineage"] as const,
  qualityHolds: (farmId: string, batchId: string) =>
    ["farms", farmId, "crop-batches", batchId, "quality-holds"] as const,
};
