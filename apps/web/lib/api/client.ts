import { triggerSessionRecovery } from "@/lib/auth/sessionRecovery";
import { errorFromNetworkFailure, errorFromResponse } from "@/lib/errors/adapter";
import type { components } from "@/lib/api/schema.gen";

export type FarmRead = components["schemas"]["FarmRead"];
export type LocationTreeNode = components["schemas"]["LocationTreeNode"];
export type LocationRead = components["schemas"]["LocationRead"];
export type CropBatchRead = components["schemas"]["CropBatchRead"];
export type BatchStageRunRead = components["schemas"]["BatchStageRunRead"];
export type BatchLineageRead = components["schemas"]["BatchLineageRead"];
// The backend has two distinct `QualityHoldRead` schemas (crop-batch
// quality holds vs. a traceability-context representation) disambiguated
// by FastAPI's OpenAPI generation using their module path.
export type QualityHoldRead = components["schemas"]["app__schemas__quality_hold__QualityHoldRead"];
export type BatchOperationalContext = components["schemas"]["BatchOperationalContext"];
export type PlacementFacts = components["schemas"]["PlacementFacts"];
export type BatchPlacement = components["schemas"]["BatchPlacement"];
export type SowingOrigin = components["schemas"]["SowingOrigin"];
export type OperationalStageSummary = components["schemas"]["OperationalStageSummary"];
export type SubtreeOccupancyRead = components["schemas"]["SubtreeOccupancyRead"];
export type LocationAggregateCount = components["schemas"]["LocationAggregateCount"];
export type OccupiedLocation = components["schemas"]["OccupiedLocation"];
export type LocationOccupant = components["schemas"]["LocationOccupant"];
export type LocationPathSegment = components["schemas"]["LocationPathSegment"];
export type GreenhouseOverviewItem = components["schemas"]["GreenhouseOverviewItem"];
export type GreenhouseSetupCreate = components["schemas"]["GreenhouseSetupCreate"];
export type GreenhouseSetupResult = components["schemas"]["GreenhouseSetupResult"];
export type GreenhouseStructureRead = components["schemas"]["GreenhouseStructureRead"];
export type SeedLotCreate = components["schemas"]["SeedLotCreate"];
export type SeedLotRead = components["schemas"]["SeedLotRead"];
export type SowNewBatchCreate = components["schemas"]["SowNewBatchCreate"];
export type SowingEventRead = components["schemas"]["SowingEventRead"];
export type AvailableSeedTrayRead = components["schemas"]["AvailableSeedTrayRead"];
export type CropSummary = components["schemas"]["CropSummary"];
export type VarietySummary = components["schemas"]["VarietySummary"];
export type CropRead = components["schemas"]["CropRead"];
export type VarietyRead = components["schemas"]["VarietyRead"];
export type SeedLotBatchSummary = components["schemas"]["SeedLotBatchSummary"];
export type AssetRead = components["schemas"]["AssetRead"];

/** `state` filter for the operational-summary list: `active` (Home) vs
 * `all` (Batch Register) -- kept as a literal union so callers/cache keys
 * can't drift from what the backend actually accepts. */
export type OperationalSummaryState = "active" | "all";

/**
 * One canonical, typed access layer over the read-only /api proxy (see
 * app/api/[...path]/route.ts). No page/component should call `fetch`
 * directly against a backend path -- everything goes through here so
 * error handling and typing stay consistent in one place.
 */
async function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`/api${path}`, { signal });
  } catch (cause) {
    throw errorFromNetworkFailure(cause);
  }
  if (response.status === 401) {
    // Centralized session recovery (AUTH-001B3) -- a bare upstream
    // FastAPI 401 and the BFF's own {"error":"session_expired"} are
    // handled identically here, no provider-specific body parsing.
    // Never triggered for /api/auth/bootstrap itself (that request goes
    // through fetchAuthBootstrap(), not this function) -- bootstrap's
    // own 401 is resolved by AuthBootstrapProvider/AuthGate instead, so
    // this never fights with that path.
    triggerSessionRecovery(currentReturnToPath());
  }
  if (!response.ok) {
    let detail: string | undefined;
    try {
      const body = (await response.json()) as { detail?: string };
      detail = body.detail;
    } catch {
      // response body wasn't JSON; fall back to the generic message for this status
    }
    throw errorFromResponse(response.status, detail);
  }
  return (await response.json()) as T;
}

/** FARM-SETUP-001: the one write path this client layer has -- everything
 * else here is (deliberately) read-only. Mirrors `getJson`'s error/401
 * handling exactly so a mutation failure is reported through the same
 * `AppError` machinery every read already uses. */
async function postJson<T>(path: string, body: unknown, signal?: AbortSignal): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`/api${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal,
    });
  } catch (cause) {
    throw errorFromNetworkFailure(cause);
  }
  if (response.status === 401) {
    triggerSessionRecovery(currentReturnToPath());
  }
  if (!response.ok) {
    let detail: string | undefined;
    try {
      const responseBody = (await response.json()) as { detail?: string };
      detail = responseBody.detail;
    } catch {
      // response body wasn't JSON; fall back to the generic message for this status
    }
    throw errorFromResponse(response.status, detail);
  }
  return (await response.json()) as T;
}

function currentReturnToPath(): string {
  if (typeof window === "undefined") return "/farms";
  return `${window.location.pathname}${window.location.search}`;
}

export function listFarms(signal?: AbortSignal): Promise<FarmRead[]> {
  return getJson<FarmRead[]>("/farms", signal);
}

export function getFarm(farmId: string, signal?: AbortSignal): Promise<FarmRead> {
  return getJson<FarmRead>(`/farms/${farmId}`, signal);
}

export function getLocationsTree(farmId: string, signal?: AbortSignal): Promise<LocationTreeNode[]> {
  return getJson<LocationTreeNode[]>(`/farms/${farmId}/locations/tree`, signal);
}

export function getOperationalSummary(
  farmId: string,
  state: OperationalSummaryState,
  signal?: AbortSignal,
): Promise<BatchOperationalContext[]> {
  return getJson<BatchOperationalContext[]>(
    `/farms/${farmId}/crop-batches/operational-summary?state=${state}`,
    signal,
  );
}

export function getBatchOperationalContext(
  farmId: string,
  batchId: string,
  signal?: AbortSignal,
): Promise<BatchOperationalContext> {
  return getJson<BatchOperationalContext>(
    `/farms/${farmId}/crop-batches/${batchId}/operational-context`,
    signal,
  );
}

export function getLocationSubtreeOccupancy(
  farmId: string,
  locationId: string,
  signal?: AbortSignal,
): Promise<SubtreeOccupancyRead> {
  return getJson<SubtreeOccupancyRead>(
    `/farms/${farmId}/locations/${locationId}/subtree-occupancy`,
    signal,
  );
}

export function getCropBatch(farmId: string, batchId: string, signal?: AbortSignal): Promise<CropBatchRead> {
  return getJson<CropBatchRead>(`/farms/${farmId}/crop-batches/${batchId}`, signal);
}

export function getStageHistory(
  farmId: string,
  batchId: string,
  signal?: AbortSignal,
): Promise<BatchStageRunRead[]> {
  return getJson<BatchStageRunRead[]>(`/farms/${farmId}/crop-batches/${batchId}/stage-history`, signal);
}

export function getBatchLineage(farmId: string, batchId: string, signal?: AbortSignal): Promise<BatchLineageRead> {
  return getJson<BatchLineageRead>(`/farms/${farmId}/crop-batches/${batchId}/lineage`, signal);
}

export function getQualityHolds(
  farmId: string,
  batchId: string,
  signal?: AbortSignal,
): Promise<QualityHoldRead[]> {
  return getJson<QualityHoldRead[]>(`/farms/${farmId}/crop-batches/${batchId}/quality-holds`, signal);
}

// --- FARM-SETUP-001 -----------------------------------------------------

export function getGreenhouseSetupOverview(farmId: string, signal?: AbortSignal): Promise<GreenhouseOverviewItem[]> {
  return getJson<GreenhouseOverviewItem[]>(`/farms/${farmId}/farm-setup/greenhouses`, signal);
}

export function getGreenhouseStructure(
  farmId: string,
  greenhouseId: string,
  signal?: AbortSignal,
): Promise<GreenhouseStructureRead> {
  return getJson<GreenhouseStructureRead>(`/farms/${farmId}/farm-setup/greenhouses/${greenhouseId}`, signal);
}

export function createGreenhouseSetup(
  farmId: string,
  payload: GreenhouseSetupCreate,
  signal?: AbortSignal,
): Promise<GreenhouseSetupResult> {
  return postJson<GreenhouseSetupResult>(`/farms/${farmId}/farm-setup/greenhouses`, payload, signal);
}

// --- NURSERY-OPS-001 ------------------------------------------------------

export function listCrops(signal?: AbortSignal): Promise<CropRead[]> {
  return getJson<CropRead[]>("/crops", signal);
}

export function listVarieties(cropId: string, signal?: AbortSignal): Promise<VarietyRead[]> {
  return getJson<VarietyRead[]>(`/crops/${cropId}/varieties`, signal);
}

export function listSeedLots(farmId: string, signal?: AbortSignal): Promise<SeedLotRead[]> {
  return getJson<SeedLotRead[]>(`/farms/${farmId}/seed-lots`, signal);
}

export function getSeedLot(farmId: string, seedLotId: string, signal?: AbortSignal): Promise<SeedLotRead> {
  return getJson<SeedLotRead>(`/farms/${farmId}/seed-lots/${seedLotId}`, signal);
}

export function registerSeedLot(farmId: string, payload: SeedLotCreate, signal?: AbortSignal): Promise<SeedLotRead> {
  return postJson<SeedLotRead>(`/farms/${farmId}/seed-lots`, payload, signal);
}

export function listAvailableSeedTrays(farmId: string, signal?: AbortSignal): Promise<AvailableSeedTrayRead[]> {
  return getJson<AvailableSeedTrayRead[]>(`/farms/${farmId}/nursery/seed-trays/available`, signal);
}

export function sowNewBatch(
  farmId: string,
  payload: SowNewBatchCreate,
  signal?: AbortSignal,
): Promise<SowingEventRead> {
  return postJson<SowingEventRead>(`/farms/${farmId}/nursery/sowings`, payload, signal);
}

export function listSowings(farmId: string, batchId: string, signal?: AbortSignal): Promise<SowingEventRead[]> {
  return getJson<SowingEventRead[]>(`/farms/${farmId}/crop-batches/${batchId}/sowings`, signal);
}

export function listAssets(farmId: string, assetType?: string, signal?: AbortSignal): Promise<AssetRead[]> {
  const query = assetType ? `?asset_type=${encodeURIComponent(assetType)}` : "";
  return getJson<AssetRead[]>(`/farms/${farmId}/assets${query}`, signal);
}

export function listBatchesForSeedLot(
  farmId: string,
  seedLotId: string,
  signal?: AbortSignal,
): Promise<SeedLotBatchSummary[]> {
  return getJson<SeedLotBatchSummary[]>(`/farms/${farmId}/seed-lots/${seedLotId}/crop-batches`, signal);
}
