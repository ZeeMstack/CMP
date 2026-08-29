import { triggerSessionRecovery } from "@/lib/auth/sessionRecovery";
import { errorFromNetworkFailure, errorFromResponse } from "@/lib/errors/adapter";
import type { components } from "@/lib/api/schema.gen";

export type FarmRead = components["schemas"]["FarmRead"];
export type FarmCreate = components["schemas"]["FarmCreate"];
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
export type CarrierTypeRead = components["schemas"]["CarrierTypeRead"];
export type CarrierSpecificationRead = components["schemas"]["CarrierSpecificationRead"];
export type CarrierSpecificationCreate = components["schemas"]["CarrierSpecificationCreate"];
export type CarrierSpecificationUpdate = components["schemas"]["CarrierSpecificationUpdate"];
export type IntersaladsTransplantCreate = components["schemas"]["IntersaladsTransplantCreate"];
export type IntersaladsTransplantRead = components["schemas"]["IntersaladsTransplantRead"];
export type AvailableNurseryCultivationPlateRead = components["schemas"]["AvailableNurseryCultivationPlateRead"];
export type LeafyProductionTransferCreate = components["schemas"]["LeafyProductionTransferCreate"];
export type LeafyProductionTransferRead = components["schemas"]["LeafyProductionTransferRead"];
export type AvailableLeafyProductionSourceRead = components["schemas"]["AvailableLeafyProductionSourceRead"];
export type AvailableProductionCultivationPlateRead = components["schemas"]["AvailableProductionCultivationPlateRead"];
export type ActiveProductionPlateRead = components["schemas"]["ActiveProductionPlateRead"];
export type RecordProductionDispositionCreate = components["schemas"]["RecordProductionDispositionCreate"];
export type ProductionDispositionRecordResult = components["schemas"]["ProductionDispositionRecordResult"];
export type CorrectProductionDispositionCreate = components["schemas"]["CorrectProductionDispositionCreate"];
export type ProductionDispositionCorrectResult = components["schemas"]["ProductionDispositionCorrectResult"];
export type ProductionDispositionHistoryRead = components["schemas"]["ProductionDispositionHistoryRead"];
export type ProductionDispositionEventRead = components["schemas"]["ProductionDispositionEventRead"];
export type TargetOccupantsRead = components["schemas"]["TargetOccupantsRead"];
export type OccupancyRead = components["schemas"]["OccupancyRead"];

// --- PILOT-SETUP-001B3 -----------------------------------------------------
// Platform Admin Tenant onboarding: read the Tenant list/detail and run the
// one onboarding command (create Tenant + resolve/create its initial admin
// User + establish an active tenant_admin Membership). Deliberately never
// under /farms/{farmId} or gated by a selected tenant -- see
// app/api/[...path]/route.ts, which routes every `/platform/*` call through
// the same tenant-unscoped identity resolution as GET /auth/me.
export type TenantRead = components["schemas"]["TenantRead"];
export type PlatformTenantOnboardingCreate = components["schemas"]["PlatformTenantOnboardingCreate"];
export type PlatformTenantOnboardingResponse = components["schemas"]["PlatformTenantOnboardingResponse"];

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
/** Most routes' error body is `{"detail": "<string>"}`. A narrow, additive
 * set of routes (HARVEST-OPS-001 SLICE 2 CORRECTION 1's Leafy Harvest
 * conflicts) instead send `{"detail": {"message": "<string>", "code":
 * "<STABLE_CODE>"}}` so the frontend can branch on `code` rather than
 * parsing message text/shape. Both shapes are handled here, once, so
 * `getJson`/`postJson` never duplicate the narrowing logic; every other
 * route's plain-string shape keeps working exactly as before. */
function parseErrorDetail(body: unknown): { message?: string; code: string | null } {
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string") return { message: detail, code: null };
  if (detail && typeof detail === "object") {
    const { message, code } = detail as { message?: unknown; code?: unknown };
    return {
      message: typeof message === "string" ? message : undefined,
      code: typeof code === "string" ? code : null,
    };
  }
  return { message: undefined, code: null };
}

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
    let code: string | null = null;
    try {
      const parsed = parseErrorDetail(await response.json());
      detail = parsed.message;
      code = parsed.code;
    } catch {
      // response body wasn't JSON; fall back to the generic message for this status
    }
    throw errorFromResponse(response.status, detail, code);
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
    let code: string | null = null;
    try {
      const parsed = parseErrorDetail(await response.json());
      detail = parsed.message;
      code = parsed.code;
    } catch {
      // response body wasn't JSON; fall back to the generic message for this status
    }
    throw errorFromResponse(response.status, detail, code);
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

export function createFarm(payload: FarmCreate, signal?: AbortSignal): Promise<FarmRead> {
  return postJson<FarmRead>("/farms", payload, signal);
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

// --- CARRIER-CONFIG-001 ---------------------------------------------------
// Tenant-scoped, deliberately never under /farms/{farmId} -- the same
// reusable physical Carrier Specification (e.g. "200 Cell Tray") may be
// used by Carriers across several of this tenant's farms.

export function listCarrierTypes(signal?: AbortSignal): Promise<CarrierTypeRead[]> {
  return getJson<CarrierTypeRead[]>("/carrier-types", signal);
}

export function listCarrierSpecifications(signal?: AbortSignal): Promise<CarrierSpecificationRead[]> {
  return getJson<CarrierSpecificationRead[]>("/carrier-specifications", signal);
}

export function getCarrierSpecification(
  specificationId: string,
  signal?: AbortSignal,
): Promise<CarrierSpecificationRead> {
  return getJson<CarrierSpecificationRead>(`/carrier-specifications/${specificationId}`, signal);
}

export function createCarrierSpecification(
  payload: CarrierSpecificationCreate,
  signal?: AbortSignal,
): Promise<CarrierSpecificationRead> {
  return postJson<CarrierSpecificationRead>("/carrier-specifications", payload, signal);
}

export function updateCarrierSpecification(
  specificationId: string,
  payload: CarrierSpecificationUpdate,
  signal?: AbortSignal,
): Promise<CarrierSpecificationRead> {
  return postJson<CarrierSpecificationRead>(`/carrier-specifications/${specificationId}/update`, payload, signal);
}

export function deactivateCarrierSpecification(
  specificationId: string,
  signal?: AbortSignal,
): Promise<CarrierSpecificationRead> {
  return postJson<CarrierSpecificationRead>(`/carrier-specifications/${specificationId}/deactivate`, {}, signal);
}

export function reactivateCarrierSpecification(
  specificationId: string,
  signal?: AbortSignal,
): Promise<CarrierSpecificationRead> {
  return postJson<CarrierSpecificationRead>(`/carrier-specifications/${specificationId}/reactivate`, {}, signal);
}

// --- NURSERY-OPS-004B.1/004B.2 ----------------------------------------------
// InterSalads Transplant: composite biological Transplant + physical Plate
// placement, one atomic command. `listAvailableIntersaladsPlates` is the
// narrow 004B.2 read backing the destination-Plate picker.

export function recordIntersaladsTransplant(
  farmId: string,
  batchId: string,
  payload: IntersaladsTransplantCreate,
  signal?: AbortSignal,
): Promise<IntersaladsTransplantRead> {
  return postJson<IntersaladsTransplantRead>(
    `/farms/${farmId}/crop-batches/${batchId}/intersalads-transplants`, payload, signal,
  );
}

export function listAvailableIntersaladsPlates(
  farmId: string,
  signal?: AbortSignal,
): Promise<AvailableNurseryCultivationPlateRead[]> {
  return getJson<AvailableNurseryCultivationPlateRead[]>(
    `/farms/${farmId}/nursery/intersalads/available-plates`, signal,
  );
}

// --- NURSERY-OPS-005B --------------------------------------------------------
// Leafy Production Transfer: composite biological Transplant (Nursery
// Cultivation Plate source) + physical Production Cultivation Plate
// placement on a Leafy Table, one atomic command. `listAvailableLeafy
// ProductionSources`/`listAvailableProductionPlates` are the narrow reads
// backing the source- and destination-Plate pickers.

export function recordLeafyProductionTransfer(
  farmId: string,
  batchId: string,
  payload: LeafyProductionTransferCreate,
  signal?: AbortSignal,
): Promise<LeafyProductionTransferRead> {
  return postJson<LeafyProductionTransferRead>(
    `/farms/${farmId}/crop-batches/${batchId}/leafy-production-transfers`, payload, signal,
  );
}

export function listAvailableLeafyProductionSources(
  farmId: string,
  batchId?: string,
  signal?: AbortSignal,
): Promise<AvailableLeafyProductionSourceRead[]> {
  const query = batchId ? `?batch_id=${encodeURIComponent(batchId)}` : "";
  return getJson<AvailableLeafyProductionSourceRead[]>(
    `/farms/${farmId}/leafy-production/available-sources${query}`, signal,
  );
}

export function listAvailableProductionPlates(
  farmId: string,
  signal?: AbortSignal,
): Promise<AvailableProductionCultivationPlateRead[]> {
  return getJson<AvailableProductionCultivationPlateRead[]>(
    `/farms/${farmId}/leafy-production/available-plates`, signal,
  );
}

// --- LEAFY-OPS-001 -------------------------------------------------------------
// Production Biological Disposition: authoritative living-population record/
// correct against a Production Cultivation Plate's active BatchCarrierAssignment,
// plus the Active Production Plates / Plant Loss History workspace reads.

export function listActiveProductionPlates(
  farmId: string,
  batchId?: string,
  signal?: AbortSignal,
): Promise<ActiveProductionPlateRead[]> {
  const query = batchId ? `?batch_id=${encodeURIComponent(batchId)}` : "";
  return getJson<ActiveProductionPlateRead[]>(`/farms/${farmId}/leafy-production/active-plates${query}`, signal);
}

export function recordProductionDisposition(
  farmId: string,
  payload: RecordProductionDispositionCreate,
  signal?: AbortSignal,
): Promise<ProductionDispositionRecordResult> {
  return postJson<ProductionDispositionRecordResult>(
    `/farms/${farmId}/leafy-production/dispositions`, payload, signal,
  );
}

export function correctProductionDisposition(
  farmId: string,
  eventId: string,
  payload: CorrectProductionDispositionCreate,
  signal?: AbortSignal,
): Promise<ProductionDispositionCorrectResult> {
  return postJson<ProductionDispositionCorrectResult>(
    `/farms/${farmId}/leafy-production/dispositions/${eventId}/correct`, payload, signal,
  );
}

export function listProductionDispositionHistory(
  farmId: string,
  params: { batchCarrierAssignmentId?: string; batchId?: string } = {},
  signal?: AbortSignal,
): Promise<ProductionDispositionHistoryRead[]> {
  const search = new URLSearchParams();
  if (params.batchCarrierAssignmentId) search.set("batch_carrier_assignment_id", params.batchCarrierAssignmentId);
  if (params.batchId) search.set("batch_id", params.batchId);
  const query = search.toString() ? `?${search.toString()}` : "";
  return getJson<ProductionDispositionHistoryRead[]>(`/farms/${farmId}/leafy-production/dispositions${query}`, signal);
}

// --- HARVEST-OPS-001 SLICE 2 -----------------------------------------------------
// Operator-facing Leafy Harvest surface: harvestable Production Plates,
// recording, history (original vs. current-effective vs. available-after-
// Packing), and line-level correction. Layers on Slice 1's frozen backend
// domain -- never a second Harvest write path.

export type LeafyHarvestLocationRead = components["schemas"]["LeafyHarvestLocationRead"];
export type HarvestablePlateRead = components["schemas"]["HarvestablePlateRead"];
export type RecordLeafyHarvestCreate = components["schemas"]["RecordLeafyHarvestCreate"];
export type RecordLeafyHarvestSourceLineIn = components["schemas"]["RecordLeafyHarvestSourceLineIn"];
export type LeafyHarvestEventRead = components["schemas"]["LeafyHarvestEventRead"];
export type LeafyHarvestSourceLineRead = components["schemas"]["LeafyHarvestSourceLineRead"];
export type LeafyHarvestSourceLineCorrectionRead = components["schemas"]["LeafyHarvestSourceLineCorrectionRead"];
export type CorrectLeafyHarvestSourceLineCreate = components["schemas"]["CorrectLeafyHarvestSourceLineCreate"];

export function listHarvestablePlates(
  farmId: string,
  batchId?: string,
  signal?: AbortSignal,
): Promise<HarvestablePlateRead[]> {
  const query = batchId ? `?batch_id=${encodeURIComponent(batchId)}` : "";
  return getJson<HarvestablePlateRead[]>(`/farms/${farmId}/leafy-production/harvestable-plates${query}`, signal);
}

export function recordLeafyHarvest(
  farmId: string,
  payload: RecordLeafyHarvestCreate,
  signal?: AbortSignal,
): Promise<LeafyHarvestEventRead> {
  return postJson<LeafyHarvestEventRead>(`/farms/${farmId}/leafy-production/harvests`, payload, signal);
}

export function listLeafyHarvests(
  farmId: string,
  batchId?: string,
  signal?: AbortSignal,
): Promise<LeafyHarvestEventRead[]> {
  const query = batchId ? `?batch_id=${encodeURIComponent(batchId)}` : "";
  return getJson<LeafyHarvestEventRead[]>(`/farms/${farmId}/leafy-production/harvests${query}`, signal);
}

export function getLeafyHarvest(
  farmId: string,
  harvestEventId: string,
  signal?: AbortSignal,
): Promise<LeafyHarvestEventRead> {
  return getJson<LeafyHarvestEventRead>(`/farms/${farmId}/leafy-production/harvests/${harvestEventId}`, signal);
}

export function correctLeafyHarvestSourceLine(
  farmId: string,
  harvestEventId: string,
  harvestSourceLineId: string,
  payload: CorrectLeafyHarvestSourceLineCreate,
  signal?: AbortSignal,
): Promise<LeafyHarvestEventRead> {
  return postJson<LeafyHarvestEventRead>(
    `/farms/${farmId}/leafy-production/harvests/${harvestEventId}/source-lines/${harvestSourceLineId}/correct`,
    payload,
    signal,
  );
}

export function getLocationOccupants(
  farmId: string,
  locationId: string,
  signal?: AbortSignal,
): Promise<TargetOccupantsRead> {
  return getJson<TargetOccupantsRead>(`/farms/${farmId}/locations/${locationId}/occupants`, signal);
}

// --- POSTHARVEST-OPS-001G --------------------------------------------------
// Processing & Packing UI: Grading (Harvested Produce Lot -> Graded Produce
// Lots), Graded Produce Lots read access, Packing (Graded Produce Lots ->
// Finished Goods), Finished Goods read access + storage placement. Grade
// Definition / Pack Specification config CRUD is out of scope here -- only
// the read-only pickers these commands need (active versions) are exposed.

export type HarvestedProduceLotRead = components["schemas"]["app__schemas__harvest__HarvestedProduceLotRead"];
export type ProduceLotBalanceRead = components["schemas"]["ProduceLotBalanceRead"];

export type GradeDefinitionRead = components["schemas"]["GradeDefinitionRead"];
export type GradeDefinitionVersionRead = components["schemas"]["GradeDefinitionVersionRead"];
export type GradingEventCreate = components["schemas"]["GradingEventCreate"];
export type GradingOutputIn = components["schemas"]["GradingOutputIn"];
export type GradingEventRead = components["schemas"]["app__schemas__grading__GradingEventRead"];
export type GradedProduceLotRead = components["schemas"]["app__schemas__grading__GradedProduceLotRead"];
export type GradedProduceLotLedgerEntryRead = components["schemas"]["GradedProduceLotLedgerEntryRead"];
export type GradedProduceLotBalanceRead = components["schemas"]["GradedProduceLotBalanceRead"];
export type GradingReversalEventCreate = components["schemas"]["GradingReversalEventCreate"];
export type GradingReversalEventRead = components["schemas"]["GradingReversalEventRead"];

export type PackSpecificationRead = components["schemas"]["PackSpecificationRead"];
export type PackSpecificationVersionRead = components["schemas"]["PackSpecificationVersionRead"];
export type PackingEventCreate = components["schemas"]["PackingEventCreate"];
export type PackingInputLineIn = components["schemas"]["PackingInputLineIn"];
export type PackingEventRead = components["schemas"]["app__schemas__packing__PackingEventRead"];
export type PackingReversalEventCreate = components["schemas"]["PackingReversalEventCreate"];
export type PackingReversalEventRead = components["schemas"]["PackingReversalEventRead"];
export type FinishedGoodsLotRead = components["schemas"]["app__schemas__packing__FinishedGoodsLotRead"];
export type FinishedGoodsLedgerEntryRead = components["schemas"]["FinishedGoodsLedgerEntryRead"];
export type FinishedGoodsBalanceRead = components["schemas"]["FinishedGoodsBalanceRead"];
export type FinishedGoodsPlacementRead = components["schemas"]["FinishedGoodsPlacementRead"];
export type LocationInventoryRead = components["schemas"]["LocationInventoryRead"];

export type RecallCaseSummaryRead = components["schemas"]["RecallCaseSummaryRead"];
export type RecallCaseDetailRead = components["schemas"]["RecallCaseDetailRead"];
export type RecallCaseCreate = components["schemas"]["RecallCaseCreate"];
export type RecallCaseClose = components["schemas"]["RecallCaseClose"];

export type DispatchEventCreate = components["schemas"]["DispatchEventCreate"];
export type DispatchLineIn = components["schemas"]["DispatchLineIn"];
export type DispatchEventRead = components["schemas"]["DispatchEventRead"];

export type FinishedGoodsStorageMovementCreate = components["schemas"]["FinishedGoodsStorageMovementCreate"];
export type FinishedGoodsStorageMovementRead = components["schemas"]["FinishedGoodsStorageMovementRead"];

// Harvested Produce Lots read access (the write/record path is Harvest,
// HARVEST-OPS-001) -- this is Grading's "pick a source Lot" surface.

export function listHarvestedProduceLots(farmId: string, signal?: AbortSignal): Promise<HarvestedProduceLotRead[]> {
  return getJson<HarvestedProduceLotRead[]>(`/farms/${farmId}/harvested-produce-lots`, signal);
}

export function getHarvestedProduceLotBalance(
  farmId: string,
  produceLotId: string,
  signal?: AbortSignal,
): Promise<ProduceLotBalanceRead> {
  return getJson<ProduceLotBalanceRead>(`/farms/${farmId}/harvested-produce-lots/${produceLotId}/balance`, signal);
}

// Grade Definitions -- tenant-scoped config, read-only here (the version
// picker Grading's output lines need). Creating/activating Grade
// Definitions/Versions is out of this ticket's scope.

export function listGradeDefinitions(
  cropId?: string,
  signal?: AbortSignal,
): Promise<GradeDefinitionRead[]> {
  const query = cropId ? `?crop_id=${encodeURIComponent(cropId)}` : "";
  return getJson<GradeDefinitionRead[]>(`/grade-definitions${query}`, signal);
}

export function listGradeDefinitionVersions(
  gradeDefinitionId: string,
  status: string | undefined,
  signal?: AbortSignal,
): Promise<GradeDefinitionVersionRead[]> {
  const query = status ? `?status=${encodeURIComponent(status)}` : "";
  return getJson<GradeDefinitionVersionRead[]>(`/grade-definitions/${gradeDefinitionId}/versions${query}`, signal);
}

// Grading -- the operator command that consumes a Harvested Produce Lot and
// produces one or more Graded Produce Lots, with full reconciliation
// (rejection/loss/sample/remainder).

export function recordGrading(
  farmId: string,
  payload: GradingEventCreate,
  signal?: AbortSignal,
): Promise<GradingEventRead> {
  return postJson<GradingEventRead>(`/farms/${farmId}/grading-events`, payload, signal);
}

export function listGradingEvents(
  farmId: string,
  sourceHarvestedProduceLotId?: string,
  signal?: AbortSignal,
): Promise<GradingEventRead[]> {
  const query = sourceHarvestedProduceLotId
    ? `?source_harvested_produce_lot_id=${encodeURIComponent(sourceHarvestedProduceLotId)}`
    : "";
  return getJson<GradingEventRead[]>(`/farms/${farmId}/grading-events${query}`, signal);
}

export function getGradingEvent(farmId: string, gradingEventId: string, signal?: AbortSignal): Promise<GradingEventRead> {
  return getJson<GradingEventRead>(`/farms/${farmId}/grading-events/${gradingEventId}`, signal);
}

// POSTHARVEST-OPS-001H: whole-event reversal only -- never a field-by-field
// correction. Reversing a GradingEvent is blocked while any output Graded
// Produce Lot is still consumed by an ACTIVE (non-reversed) Packing Event.

export function reverseGradingEvent(
  farmId: string,
  gradingEventId: string,
  payload: GradingReversalEventCreate,
  signal?: AbortSignal,
): Promise<GradingReversalEventRead> {
  return postJson<GradingReversalEventRead>(
    `/farms/${farmId}/grading-events/${gradingEventId}/reversal`, payload, signal,
  );
}

export function getGradingReversalEvent(
  farmId: string,
  gradingEventId: string,
  signal?: AbortSignal,
): Promise<GradingReversalEventRead> {
  return getJson<GradingReversalEventRead>(`/farms/${farmId}/grading-events/${gradingEventId}/reversal`, signal);
}

export function listGradedProduceLots(
  farmId: string,
  params: { cropId?: string; varietyId?: string; gradeDefinitionVersionId?: string } = {},
  signal?: AbortSignal,
): Promise<GradedProduceLotRead[]> {
  const search = new URLSearchParams();
  if (params.cropId) search.set("crop_id", params.cropId);
  if (params.varietyId) search.set("variety_id", params.varietyId);
  if (params.gradeDefinitionVersionId) search.set("grade_definition_version_id", params.gradeDefinitionVersionId);
  const query = search.toString() ? `?${search.toString()}` : "";
  return getJson<GradedProduceLotRead[]>(`/farms/${farmId}/graded-produce-lots${query}`, signal);
}

export function getGradedProduceLot(
  farmId: string,
  gradedProduceLotId: string,
  signal?: AbortSignal,
): Promise<GradedProduceLotRead> {
  return getJson<GradedProduceLotRead>(`/farms/${farmId}/graded-produce-lots/${gradedProduceLotId}`, signal);
}

export function getGradedProduceLotLedger(
  farmId: string,
  gradedProduceLotId: string,
  signal?: AbortSignal,
): Promise<GradedProduceLotLedgerEntryRead[]> {
  return getJson<GradedProduceLotLedgerEntryRead[]>(
    `/farms/${farmId}/graded-produce-lots/${gradedProduceLotId}/ledger`, signal,
  );
}

export function getGradedProduceLotBalance(
  farmId: string,
  gradedProduceLotId: string,
  signal?: AbortSignal,
): Promise<GradedProduceLotBalanceRead> {
  return getJson<GradedProduceLotBalanceRead>(
    `/farms/${farmId}/graded-produce-lots/${gradedProduceLotId}/balance`, signal,
  );
}

// Pack Specifications -- tenant-scoped config, read-only here (the version
// picker Packing needs). Creating/activating Pack Specifications/Versions is
// out of this ticket's scope.

export function listPackSpecifications(cropId?: string, signal?: AbortSignal): Promise<PackSpecificationRead[]> {
  const query = cropId ? `?crop_id=${encodeURIComponent(cropId)}` : "";
  return getJson<PackSpecificationRead[]>(`/pack-specifications${query}`, signal);
}

export function listPackSpecificationVersions(
  packSpecificationId: string,
  status: string | undefined,
  signal?: AbortSignal,
): Promise<PackSpecificationVersionRead[]> {
  const query = status ? `?status=${encodeURIComponent(status)}` : "";
  return getJson<PackSpecificationVersionRead[]>(
    `/pack-specifications/${packSpecificationId}/versions${query}`, signal,
  );
}

// Packing -- the operator command that consumes one or more Graded Produce
// Lots and produces one Finished Goods Lot, with reconciliation (process
// loss/rejection).

export function recordPacking(farmId: string, payload: PackingEventCreate, signal?: AbortSignal): Promise<PackingEventRead> {
  return postJson<PackingEventRead>(`/farms/${farmId}/packing-events`, payload, signal);
}

export function listPackingEvents(farmId: string, signal?: AbortSignal): Promise<PackingEventRead[]> {
  return getJson<PackingEventRead[]>(`/farms/${farmId}/packing-events`, signal);
}

export function getPackingEvent(farmId: string, packingEventId: string, signal?: AbortSignal): Promise<PackingEventRead> {
  return getJson<PackingEventRead>(`/farms/${farmId}/packing-events/${packingEventId}`, signal);
}

// POSTHARVEST-OPS-001H: whole-event reversal only -- never a field-by-field
// correction. Reversing a PackingEvent is blocked while its Finished Goods
// Lot has any dispatch activity or a nonzero net placed quantity in cold
// storage.

export function reversePackingEvent(
  farmId: string,
  packingEventId: string,
  payload: PackingReversalEventCreate,
  signal?: AbortSignal,
): Promise<PackingReversalEventRead> {
  return postJson<PackingReversalEventRead>(
    `/farms/${farmId}/packing-events/${packingEventId}/reversal`, payload, signal,
  );
}

export function getPackingReversalEvent(
  farmId: string,
  packingEventId: string,
  signal?: AbortSignal,
): Promise<PackingReversalEventRead> {
  return getJson<PackingReversalEventRead>(`/farms/${farmId}/packing-events/${packingEventId}/reversal`, signal);
}

export function listFinishedGoodsLots(farmId: string, signal?: AbortSignal): Promise<FinishedGoodsLotRead[]> {
  return getJson<FinishedGoodsLotRead[]>(`/farms/${farmId}/finished-goods-lots`, signal);
}

export function getFinishedGoodsLot(
  farmId: string,
  finishedGoodsLotId: string,
  signal?: AbortSignal,
): Promise<FinishedGoodsLotRead> {
  return getJson<FinishedGoodsLotRead>(`/farms/${farmId}/finished-goods-lots/${finishedGoodsLotId}`, signal);
}

export function getFinishedGoodsLedger(
  farmId: string,
  finishedGoodsLotId: string,
  signal?: AbortSignal,
): Promise<FinishedGoodsLedgerEntryRead[]> {
  return getJson<FinishedGoodsLedgerEntryRead[]>(
    `/farms/${farmId}/finished-goods-lots/${finishedGoodsLotId}/ledger`, signal,
  );
}

export function getFinishedGoodsBalance(
  farmId: string,
  finishedGoodsLotId: string,
  signal?: AbortSignal,
): Promise<FinishedGoodsBalanceRead> {
  return getJson<FinishedGoodsBalanceRead>(
    `/farms/${farmId}/finished-goods-lots/${finishedGoodsLotId}/balance`, signal,
  );
}

export function getFinishedGoodsPlacement(
  farmId: string,
  finishedGoodsLotId: string,
  signal?: AbortSignal,
): Promise<FinishedGoodsPlacementRead> {
  return getJson<FinishedGoodsPlacementRead>(
    `/farms/${farmId}/finished-goods-lots/${finishedGoodsLotId}/placements`, signal,
  );
}

// Recall -- read-only here, so Graded Produce Lot / Finished Goods Lot
// screens can flag "under an open recall" without a dedicated
// recall-flag-per-lot endpoint (none exists; this is a client-side join
// over the farm's recall case list, same approach documented for the
// traceability surface).

export function listRecallCases(farmId: string, signal?: AbortSignal): Promise<RecallCaseSummaryRead[]> {
  return getJson<RecallCaseSummaryRead[]>(`/farms/${farmId}/recall-cases`, signal);
}

export function getRecallCase(farmId: string, recallCaseId: string, signal?: AbortSignal): Promise<RecallCaseDetailRead> {
  return getJson<RecallCaseDetailRead>(`/farms/${farmId}/recall-cases/${recallCaseId}`, signal);
}

export function openRecallCase(farmId: string, payload: RecallCaseCreate, signal?: AbortSignal): Promise<RecallCaseDetailRead> {
  return postJson<RecallCaseDetailRead>(`/farms/${farmId}/recall-cases`, payload, signal);
}

export function closeRecallCase(
  farmId: string,
  recallCaseId: string,
  payload: RecallCaseClose,
  signal?: AbortSignal,
): Promise<RecallCaseDetailRead> {
  return postJson<RecallCaseDetailRead>(`/farms/${farmId}/recall-cases/${recallCaseId}/close`, payload, signal);
}

// PILOT-READY-001: Cold Storage (place/transfer/release a Finished Goods
// Lot against a Location) and Dispatch (consume a Finished Goods Lot's
// currently-unplaced balance, CMP-018) -- both previously had no frontend
// write path despite full backend support.

export function recordFinishedGoodsStorageMovement(
  farmId: string,
  payload: FinishedGoodsStorageMovementCreate,
  signal?: AbortSignal,
): Promise<FinishedGoodsStorageMovementRead> {
  return postJson<FinishedGoodsStorageMovementRead>(`/farms/${farmId}/finished-goods-storage-movements`, payload, signal);
}

export function listFinishedGoodsStorageMovements(
  farmId: string,
  finishedGoodsLotId: string,
  signal?: AbortSignal,
): Promise<FinishedGoodsStorageMovementRead[]> {
  return getJson<FinishedGoodsStorageMovementRead[]>(
    `/farms/${farmId}/finished-goods-lots/${finishedGoodsLotId}/storage-movements`, signal,
  );
}

export function recordDispatch(farmId: string, payload: DispatchEventCreate, signal?: AbortSignal): Promise<DispatchEventRead> {
  return postJson<DispatchEventRead>(`/farms/${farmId}/dispatches`, payload, signal);
}

export function listDispatchEvents(farmId: string, signal?: AbortSignal): Promise<DispatchEventRead[]> {
  return getJson<DispatchEventRead[]>(`/farms/${farmId}/dispatches`, signal);
}

// UI-OPT-001: Traceability -- read-only backward/forward trace, backed by
// backend endpoints that already existed before this ticket (a full
// backward trace from a Finished Goods Lot, and a forward "impact" trace
// from a Crop Batch or a Harvested Produce Lot). No new backend genealogy
// logic is introduced here -- this is only the frontend client for reads
// that were already implemented.

export type FinishedGoodsLotTraceRead = components["schemas"]["FinishedGoodsLotTraceRead"];
export type CropBatchImpactRead = components["schemas"]["CropBatchImpactRead"];
export type HarvestedProduceLotImpactRead = components["schemas"]["HarvestedProduceLotImpactRead"];
export type ImpactSummary = components["schemas"]["ImpactSummary"];
export type TraceCompleteness = components["schemas"]["Completeness"];
export type TraceLineage = components["schemas"]["Lineage"];
export type CropBatchNode = components["schemas"]["CropBatchNode"];
export type FinishedGoodsLotImpactRead = components["schemas"]["FinishedGoodsLotImpactRead"];
export type SeedOrigin = components["schemas"]["SeedOrigin"];
export type StorageMovementRead = components["schemas"]["StorageMovementRead"];
// Every `Trace*` alias below disambiguates the backend's trace-context
// read model from the unrelated, differently-shaped, same-named schema
// already exported above for the live write-side screens (Grading/Packing/
// Dispatch) -- same rationale as the pre-existing `QualityHoldRead` split.
export type TraceHarvestedProduceLotRead = components["schemas"]["app__schemas__traceability__HarvestedProduceLotRead"];
export type TraceGradedProduceLotRead = components["schemas"]["app__schemas__traceability__GradedProduceLotRead"];
export type TraceGradingEventRead = components["schemas"]["app__schemas__traceability__GradingEventRead"];
export type TracePackingEventRead = components["schemas"]["app__schemas__traceability__PackingEventRead"];
export type TracePackingInputLineRead = components["schemas"]["app__schemas__traceability__PackingInputLineRead"];
export type TraceHarvestEventRead = components["schemas"]["app__schemas__traceability__HarvestEventRead"];
export type TraceDispatchLineRead = components["schemas"]["app__schemas__traceability__DispatchLineRead"];
export type TraceLocationBalanceRead = components["schemas"]["app__schemas__traceability__LocationBalanceRead"];
export type TraceQualityHoldRead = components["schemas"]["app__schemas__traceability__QualityHoldRead"];

export function getFinishedGoodsLotTrace(
  farmId: string,
  finishedGoodsLotId: string,
  signal?: AbortSignal,
): Promise<FinishedGoodsLotTraceRead> {
  return getJson<FinishedGoodsLotTraceRead>(
    `/farms/${farmId}/traceability/finished-goods-lots/${finishedGoodsLotId}`, signal,
  );
}

export function getCropBatchImpact(farmId: string, batchId: string, signal?: AbortSignal): Promise<CropBatchImpactRead> {
  return getJson<CropBatchImpactRead>(`/farms/${farmId}/traceability/crop-batches/${batchId}/impact`, signal);
}

export function getHarvestedProduceLotImpact(
  farmId: string,
  produceLotId: string,
  signal?: AbortSignal,
): Promise<HarvestedProduceLotImpactRead> {
  return getJson<HarvestedProduceLotImpactRead>(
    `/farms/${farmId}/traceability/harvested-produce-lots/${produceLotId}/impact`, signal,
  );
}

// --- PILOT-SETUP-001B3 -----------------------------------------------------

export function listPlatformTenants(signal?: AbortSignal): Promise<TenantRead[]> {
  return getJson<TenantRead[]>("/platform/tenants", signal);
}

export function getPlatformTenant(tenantId: string, signal?: AbortSignal): Promise<TenantRead> {
  return getJson<TenantRead>(`/platform/tenants/${tenantId}`, signal);
}

export function createPlatformTenant(
  payload: PlatformTenantOnboardingCreate,
  signal?: AbortSignal,
): Promise<PlatformTenantOnboardingResponse> {
  return postJson<PlatformTenantOnboardingResponse>("/platform/tenants", payload, signal);
}
