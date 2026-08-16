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
export type PlaceTrolleyCreate = components["schemas"]["PlaceTrolleyCreate"];
export type PlaceTrayCreate = components["schemas"]["PlaceTrayCreate"];
export type TrolleyPlacementRead = components["schemas"]["TrolleyPlacementRead"];
export type TrayPlacementRead = components["schemas"]["TrayPlacementRead"];
export type GerminationChamberAvailabilityRead = components["schemas"]["GerminationChamberAvailabilityRead"];
export type AvailableTrolleyRead = components["schemas"]["AvailableTrolleyRead"];
export type TrolleySlotAvailabilityRead = components["schemas"]["TrolleySlotAvailabilityRead"];
export type GerminationTrayRead = components["schemas"]["GerminationTrayRead"];
export type GerminationOutcomeCommandCreate = components["schemas"]["GerminationOutcomeCommandCreate"];
export type GerminationOutcomeCommandRead = components["schemas"]["GerminationOutcomeCommandRead"];
export type GerminationOutcomeCurrentRead = components["schemas"]["GerminationOutcomeCurrentRead"];
export type GerminationOutcomeBatchAggregateRead = components["schemas"]["GerminationOutcomeBatchAggregateRead"];
export type GerminationOutcomeSnapshotRead = components["schemas"]["GerminationOutcomeSnapshotRead"];
export type SeedlingEntryCreate = components["schemas"]["SeedlingEntryCreate"];
export type SeedlingEntryRead = components["schemas"]["SeedlingEntryRead"];
export type AvailableSeedlingTableRead = components["schemas"]["AvailableSeedlingTableRead"];
export type SeedlingCandidateTrayRead = components["schemas"]["SeedlingCandidateTrayRead"];
export type SeedlingDispositionReasonRead = components["schemas"]["SeedlingDispositionReasonRead"];
export type SeedlingBiologicalTrayRead = components["schemas"]["SeedlingBiologicalTrayRead"];
export type SeedlingDispositionHistoryRead = components["schemas"]["SeedlingDispositionHistoryRead"];
export type SeedlingDispositionEventRead = components["schemas"]["SeedlingDispositionEventRead"];
export type RecordSeedlingDispositionCreate = components["schemas"]["RecordSeedlingDispositionCreate"];
export type SeedlingDispositionRecordResult = components["schemas"]["SeedlingDispositionRecordResult"];
export type CorrectSeedlingDispositionCreate = components["schemas"]["CorrectSeedlingDispositionCreate"];
export type SeedlingDispositionCorrectResult = components["schemas"]["SeedlingDispositionCorrectResult"];

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

// --- NURSERY-OPS-002A ------------------------------------------------------
// Germination Placement -- physical placement only (Trolley into Chamber,
// Seed Tray into a Trolley Slot). No biological Germination outcome here.

export function placeTrolley(
  farmId: string,
  payload: PlaceTrolleyCreate,
  signal?: AbortSignal,
): Promise<TrolleyPlacementRead> {
  return postJson<TrolleyPlacementRead>(`/farms/${farmId}/germination/trolley-placements`, payload, signal);
}

export function placeTray(
  farmId: string,
  payload: PlaceTrayCreate,
  signal?: AbortSignal,
): Promise<TrayPlacementRead> {
  return postJson<TrayPlacementRead>(`/farms/${farmId}/germination/tray-placements`, payload, signal);
}

export function listAvailableChambers(
  farmId: string,
  signal?: AbortSignal,
): Promise<GerminationChamberAvailabilityRead[]> {
  return getJson<GerminationChamberAvailabilityRead[]>(`/farms/${farmId}/germination/chambers/available`, signal);
}

export function listAvailableTrolleys(farmId: string, signal?: AbortSignal): Promise<AvailableTrolleyRead[]> {
  return getJson<AvailableTrolleyRead[]>(`/farms/${farmId}/germination/trolleys/available`, signal);
}

export function listTrolleySlots(
  farmId: string,
  trolleyId: string,
  signal?: AbortSignal,
): Promise<TrolleySlotAvailabilityRead[]> {
  return getJson<TrolleySlotAvailabilityRead[]>(`/farms/${farmId}/germination/trolleys/${trolleyId}/slots`, signal);
}

export function listGerminationTrays(farmId: string, signal?: AbortSignal): Promise<GerminationTrayRead[]> {
  return getJson<GerminationTrayRead[]>(`/farms/${farmId}/germination/trays`, signal);
}

// --- NURSERY-OPS-002B ------------------------------------------------------
// Modern, INDIVIDUAL-SEEDLING-based Germination outcome -- distinct from the
// legacy site-based GerminationCheck. Never exposed in this client layer.

export function recordGerminationOutcomes(
  farmId: string,
  batchId: string,
  payload: GerminationOutcomeCommandCreate,
  signal?: AbortSignal,
): Promise<GerminationOutcomeCommandRead> {
  return postJson<GerminationOutcomeCommandRead>(
    `/farms/${farmId}/crop-batches/${batchId}/germination-outcomes`, payload, signal,
  );
}

export function getCurrentGerminationOutcomes(
  farmId: string,
  batchId: string,
  signal?: AbortSignal,
): Promise<GerminationOutcomeBatchAggregateRead> {
  return getJson<GerminationOutcomeBatchAggregateRead>(
    `/farms/${farmId}/crop-batches/${batchId}/germination-outcomes/current`, signal,
  );
}

// --- NURSERY-OPS-003A ------------------------------------------------------
// Seedling Entry & Placement -- atomically pairs a physical Movement (Trolley
// Slot -> Seedling Table) with an immutable frozen biological handoff
// referencing the historically-valid completed Germination outcome. No
// Seedling biological loss/removal here -- that is NURSERY-OPS-003B's own,
// separate, not-yet-built scope.

export function recordSeedlingEntry(
  farmId: string,
  payload: SeedlingEntryCreate,
  signal?: AbortSignal,
): Promise<SeedlingEntryRead> {
  return postJson<SeedlingEntryRead>(`/farms/${farmId}/nursery/seedling/entries`, payload, signal);
}

export function listAvailableSeedlingTables(
  farmId: string,
  signal?: AbortSignal,
): Promise<AvailableSeedlingTableRead[]> {
  return getJson<AvailableSeedlingTableRead[]>(`/farms/${farmId}/nursery/seedling/tables/available`, signal);
}

export function listSeedlingCandidateTrays(
  farmId: string,
  signal?: AbortSignal,
): Promise<SeedlingCandidateTrayRead[]> {
  return getJson<SeedlingCandidateTrayRead[]>(`/farms/${farmId}/nursery/seedling/trays`, signal);
}

// --- NURSERY-OPS-003B ------------------------------------------------------
// Seedling Biological Dispositions -- immutable, insert-only quantity-
// reducing facts recorded AFTER SeedlingEntry (weak/disease/pest/physical
// damage, mortality, QC rejection, sample, other). Distinct from Movement
// and from Observation/Quality holds; see docs/domain/OBSERVATION_QUALITY_MODEL.md.

export function listSeedlingDispositionReasons(
  farmId: string,
  signal?: AbortSignal,
): Promise<SeedlingDispositionReasonRead[]> {
  return getJson<SeedlingDispositionReasonRead[]>(`/farms/${farmId}/nursery/seedling/disposition-reasons`, signal);
}

export function listSeedlingBiologicalTrays(
  farmId: string,
  signal?: AbortSignal,
): Promise<SeedlingBiologicalTrayRead[]> {
  return getJson<SeedlingBiologicalTrayRead[]>(`/farms/${farmId}/nursery/seedling/biological-trays`, signal);
}

export function getSeedlingDispositionHistory(
  farmId: string,
  seedlingEntryId: string,
  signal?: AbortSignal,
): Promise<SeedlingDispositionHistoryRead> {
  return getJson<SeedlingDispositionHistoryRead>(
    `/farms/${farmId}/nursery/seedling/dispositions?seedling_entry_id=${encodeURIComponent(seedlingEntryId)}`,
    signal,
  );
}

export function recordSeedlingDisposition(
  farmId: string,
  payload: RecordSeedlingDispositionCreate,
  signal?: AbortSignal,
): Promise<SeedlingDispositionRecordResult> {
  return postJson<SeedlingDispositionRecordResult>(`/farms/${farmId}/nursery/seedling/dispositions`, payload, signal);
}

export function correctSeedlingDisposition(
  farmId: string,
  eventId: string,
  payload: CorrectSeedlingDispositionCreate,
  signal?: AbortSignal,
): Promise<SeedlingDispositionCorrectResult> {
  return postJson<SeedlingDispositionCorrectResult>(
    `/farms/${farmId}/nursery/seedling/dispositions/${eventId}/correct`, payload, signal,
  );
}
