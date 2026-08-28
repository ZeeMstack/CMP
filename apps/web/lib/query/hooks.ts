"use client";

import { useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";

import * as api from "@/lib/api/client";
import type {
  CarrierSpecificationCreate,
  CarrierSpecificationUpdate,
  CorrectLeafyHarvestSourceLineCreate,
  CorrectProductionDispositionCreate,
  CorrectSeedlingDispositionCreate,
  DispatchEventCreate,
  FinishedGoodsStorageMovementCreate,
  GerminationOutcomeCommandCreate,
  GradingEventCreate,
  GradingReversalEventCreate,
  GreenhouseSetupCreate,
  IntersaladsTransplantCreate,
  LeafyProductionTransferCreate,
  PackingEventCreate,
  PackingReversalEventCreate,
  PlaceTrayCreate,
  PlaceTrolleyCreate,
  RecallCaseClose,
  RecallCaseCreate,
  RecordLeafyHarvestCreate,
  RecordProductionDispositionCreate,
  RecordSeedlingDispositionCreate,
  SeedlingEntryCreate,
  SeedLotCreate,
  SowNewBatchCreate,
} from "@/lib/api/client";
import { useAuthBootstrap } from "@/lib/auth/AuthBootstrapProvider";
import { AppError } from "@/lib/errors/adapter";
import { queryKeys } from "@/lib/query/keys";

/** staleTime tiers -- not every resource changes at the same rate. Farm and
 * location-hierarchy data is close to reference data for a pilot; batch
 * lists/detail reflect day-to-day operations and should refresh sooner. */
const STALE_REFERENCE_MS = 5 * 60_000;
const STALE_LIST_MS = 60_000;
const STALE_DETAIL_MS = 30_000;

/** Every tenant-scoped hook below reads the active tenant from
 * AuthBootstrapProvider itself (a React Context read, not a network
 * call) rather than requiring every page/component to thread a tenantId
 * prop through -- this is what keeps Home/Batch List/Batch Detail/
 * Locations completely unchanged by AUTH-001B2 (see those files). When
 * no tenant is selected yet, this returns undefined and every hook below
 * disables its query rather than issuing a request it knows must fail or
 * (worse) could resolve against the wrong tenant. */
function useSelectedTenantId(): string | undefined {
  const { bootstrap } = useAuthBootstrap();
  return bootstrap?.selectedTenantId ?? undefined;
}

export function useFarms() {
  const tenantId = useSelectedTenantId();
  return useQuery({
    queryKey: queryKeys.farms(tenantId ?? ""),
    queryFn: ({ signal }) => api.listFarms(signal),
    staleTime: STALE_REFERENCE_MS,
    enabled: Boolean(tenantId),
  });
}

export function useFarm(farmId: string) {
  const tenantId = useSelectedTenantId();
  return useQuery({
    queryKey: queryKeys.farm(tenantId ?? "", farmId),
    queryFn: ({ signal }) => api.getFarm(farmId, signal),
    staleTime: STALE_REFERENCE_MS,
    enabled: Boolean(tenantId),
  });
}

export function useLocationsTree(farmId: string) {
  const tenantId = useSelectedTenantId();
  return useQuery({
    queryKey: queryKeys.locationsTree(tenantId ?? "", farmId),
    queryFn: ({ signal }) => api.getLocationsTree(farmId, signal),
    staleTime: STALE_REFERENCE_MS,
    enabled: Boolean(tenantId),
  });
}

/** On-demand only -- callers pass `enabled: false` until a structural
 * branch is actually expanded. One request per independently-expanded
 * root; React Query's cache (keyed on `locationId`, now also on tenant)
 * prevents re-fetching the same root twice. */
export function useLocationSubtreeOccupancy(farmId: string, locationId: string, enabled: boolean) {
  const tenantId = useSelectedTenantId();
  return useQuery({
    queryKey: queryKeys.locationSubtreeOccupancy(tenantId ?? "", farmId, locationId),
    queryFn: ({ signal }) => api.getLocationSubtreeOccupancy(farmId, locationId, signal),
    staleTime: STALE_DETAIL_MS,
    enabled: Boolean(tenantId) && enabled,
  });
}

export function useOperationalSummary(farmId: string, state: "active" | "all") {
  const tenantId = useSelectedTenantId();
  return useQuery({
    queryKey: queryKeys.operationalSummary(tenantId ?? "", farmId, state),
    queryFn: ({ signal }) => api.getOperationalSummary(farmId, state, signal),
    staleTime: STALE_LIST_MS,
    enabled: Boolean(tenantId),
  });
}

export function useBatchOperationalContext(farmId: string, batchId: string) {
  const tenantId = useSelectedTenantId();
  return useQuery({
    queryKey: queryKeys.batchOperationalContext(tenantId ?? "", farmId, batchId),
    queryFn: ({ signal }) => api.getBatchOperationalContext(farmId, batchId, signal),
    staleTime: STALE_DETAIL_MS,
    enabled: Boolean(tenantId),
  });
}

export function useCropBatch(farmId: string, batchId: string) {
  const tenantId = useSelectedTenantId();
  return useQuery({
    queryKey: queryKeys.cropBatch(tenantId ?? "", farmId, batchId),
    queryFn: ({ signal }) => api.getCropBatch(farmId, batchId, signal),
    staleTime: STALE_DETAIL_MS,
    enabled: Boolean(tenantId),
  });
}

export function useStageHistory(farmId: string, batchId: string) {
  const tenantId = useSelectedTenantId();
  return useQuery({
    queryKey: queryKeys.stageHistory(tenantId ?? "", farmId, batchId),
    queryFn: ({ signal }) => api.getStageHistory(farmId, batchId, signal),
    staleTime: STALE_DETAIL_MS,
    enabled: Boolean(tenantId),
  });
}

export function useBatchLineage(farmId: string, batchId: string) {
  const tenantId = useSelectedTenantId();
  return useQuery({
    queryKey: queryKeys.batchLineage(tenantId ?? "", farmId, batchId),
    queryFn: ({ signal }) => api.getBatchLineage(farmId, batchId, signal),
    staleTime: STALE_DETAIL_MS,
    enabled: Boolean(tenantId),
  });
}

export function useQualityHolds(farmId: string, batchId: string) {
  const tenantId = useSelectedTenantId();
  return useQuery({
    queryKey: queryKeys.qualityHolds(tenantId ?? "", farmId, batchId),
    queryFn: ({ signal }) => api.getQualityHolds(farmId, batchId, signal),
    staleTime: STALE_DETAIL_MS,
    enabled: Boolean(tenantId),
  });
}

// --- FARM-SETUP-001 -------------------------------------------------------

export function useGreenhouseSetupOverview(farmId: string) {
  const tenantId = useSelectedTenantId();
  return useQuery({
    queryKey: queryKeys.greenhouseSetupOverview(tenantId ?? "", farmId),
    queryFn: ({ signal }) => api.getGreenhouseSetupOverview(farmId, signal),
    staleTime: STALE_LIST_MS,
    enabled: Boolean(tenantId),
  });
}

export function useGreenhouseStructure(farmId: string, greenhouseId: string) {
  const tenantId = useSelectedTenantId();
  return useQuery({
    queryKey: queryKeys.greenhouseStructure(tenantId ?? "", farmId, greenhouseId),
    queryFn: ({ signal }) => api.getGreenhouseStructure(farmId, greenhouseId, signal),
    staleTime: STALE_DETAIL_MS,
    enabled: Boolean(tenantId),
  });
}

/** The idempotency key (`client_command_id`) lives in the payload itself
 * (set once by the caller before the first submit attempt) -- an
 * accidental double-click or a network-retry-triggered resubmit reuses
 * the SAME payload object and therefore the same id, so the backend
 * recognizes it as a replay rather than a second Greenhouse. */
export function useCreateGreenhouseSetup(farmId: string) {
  const tenantId = useSelectedTenantId();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: GreenhouseSetupCreate) => api.createGreenhouseSetup(farmId, payload),
    onSuccess: () => {
      if (!tenantId) return;
      queryClient.invalidateQueries({ queryKey: queryKeys.greenhouseSetupOverview(tenantId, farmId) });
      queryClient.invalidateQueries({ queryKey: queryKeys.locationsTree(tenantId, farmId) });
    },
  });
}

// --- NURSERY-OPS-001 -------------------------------------------------------

export function useCrops() {
  const tenantId = useSelectedTenantId();
  return useQuery({
    queryKey: queryKeys.crops(tenantId ?? ""),
    queryFn: ({ signal }) => api.listCrops(signal),
    staleTime: STALE_REFERENCE_MS,
    enabled: Boolean(tenantId),
  });
}

export function useVarieties(cropId: string | undefined) {
  const tenantId = useSelectedTenantId();
  return useQuery({
    queryKey: queryKeys.varieties(tenantId ?? "", cropId ?? ""),
    queryFn: ({ signal }) => api.listVarieties(cropId as string, signal),
    staleTime: STALE_REFERENCE_MS,
    enabled: Boolean(tenantId) && Boolean(cropId),
  });
}

export function useSeedLots(farmId: string) {
  const tenantId = useSelectedTenantId();
  return useQuery({
    queryKey: queryKeys.seedLots(tenantId ?? "", farmId),
    queryFn: ({ signal }) => api.listSeedLots(farmId, signal),
    staleTime: STALE_LIST_MS,
    enabled: Boolean(tenantId),
  });
}

export function useSeedLot(farmId: string, seedLotId: string) {
  const tenantId = useSelectedTenantId();
  return useQuery({
    queryKey: queryKeys.seedLot(tenantId ?? "", farmId, seedLotId),
    queryFn: ({ signal }) => api.getSeedLot(farmId, seedLotId, signal),
    staleTime: STALE_DETAIL_MS,
    enabled: Boolean(tenantId),
  });
}

export function useRegisterSeedLot(farmId: string) {
  const tenantId = useSelectedTenantId();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: SeedLotCreate) => api.registerSeedLot(farmId, payload),
    onSuccess: () => {
      if (!tenantId) return;
      queryClient.invalidateQueries({ queryKey: queryKeys.seedLots(tenantId, farmId) });
    },
  });
}

export function useAvailableSeedTrays(farmId: string) {
  const tenantId = useSelectedTenantId();
  return useQuery({
    queryKey: queryKeys.availableSeedTrays(tenantId ?? "", farmId),
    queryFn: ({ signal }) => api.listAvailableSeedTrays(farmId, signal),
    staleTime: STALE_DETAIL_MS,
    enabled: Boolean(tenantId),
  });
}

export function useBatchesForSeedLot(farmId: string, seedLotId: string) {
  const tenantId = useSelectedTenantId();
  return useQuery({
    queryKey: queryKeys.seedLotBatches(tenantId ?? "", farmId, seedLotId),
    queryFn: ({ signal }) => api.listBatchesForSeedLot(farmId, seedLotId, signal),
    staleTime: STALE_DETAIL_MS,
    enabled: Boolean(tenantId),
  });
}

export function useAssets(farmId: string, assetType: string) {
  const tenantId = useSelectedTenantId();
  return useQuery({
    queryKey: queryKeys.assets(tenantId ?? "", farmId, assetType),
    queryFn: ({ signal }) => api.listAssets(farmId, assetType, signal),
    staleTime: STALE_REFERENCE_MS,
    enabled: Boolean(tenantId),
  });
}

// --- NURSERY-OPS-002A -------------------------------------------------------
// Germination Placement -- physical placement only (no biological outcome).

export function useAvailableChambers(farmId: string) {
  const tenantId = useSelectedTenantId();
  return useQuery({
    queryKey: queryKeys.availableChambers(tenantId ?? "", farmId),
    queryFn: ({ signal }) => api.listAvailableChambers(farmId, signal),
    staleTime: STALE_DETAIL_MS,
    enabled: Boolean(tenantId),
  });
}

export function useAvailableTrolleys(farmId: string) {
  const tenantId = useSelectedTenantId();
  return useQuery({
    queryKey: queryKeys.availableTrolleys(tenantId ?? "", farmId),
    queryFn: ({ signal }) => api.listAvailableTrolleys(farmId, signal),
    staleTime: STALE_DETAIL_MS,
    enabled: Boolean(tenantId),
  });
}

export function useTrolleySlots(farmId: string, trolleyId: string) {
  const tenantId = useSelectedTenantId();
  return useQuery({
    queryKey: queryKeys.trolleySlots(tenantId ?? "", farmId, trolleyId),
    queryFn: ({ signal }) => api.listTrolleySlots(farmId, trolleyId, signal),
    staleTime: STALE_DETAIL_MS,
    enabled: Boolean(tenantId) && Boolean(trolleyId),
  });
}

export function useGerminationTrays(farmId: string) {
  const tenantId = useSelectedTenantId();
  return useQuery({
    queryKey: queryKeys.germinationTrays(tenantId ?? "", farmId),
    queryFn: ({ signal }) => api.listGerminationTrays(farmId, signal),
    staleTime: STALE_DETAIL_MS,
    enabled: Boolean(tenantId),
  });
}

/** Idempotency key (`client_command_id`) lives in the payload itself, set
 * once by the caller -- same replay-safe pattern as `useSowNewBatch`. A
 * Trolley placement changes chamber occupancy (and, transitively, every
 * Tray resting on that Trolley's resolved location) and asset-level slot
 * occupancy, so both available-chambers/trolleys reads and the tray list
 * are invalidated. */
export function usePlaceTrolley(farmId: string) {
  const tenantId = useSelectedTenantId();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: PlaceTrolleyCreate) => api.placeTrolley(farmId, payload),
    onSuccess: () => {
      if (!tenantId) return;
      queryClient.invalidateQueries({ queryKey: queryKeys.availableChambers(tenantId, farmId) });
      queryClient.invalidateQueries({ queryKey: queryKeys.availableTrolleys(tenantId, farmId) });
      queryClient.invalidateQueries({ queryKey: queryKeys.germinationTrays(tenantId, farmId) });
    },
  });
}

export function usePlaceTray(farmId: string) {
  const tenantId = useSelectedTenantId();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: PlaceTrayCreate) => api.placeTray(farmId, payload),
    onSuccess: (_result, variables) => {
      if (!tenantId) return;
      queryClient.invalidateQueries({ queryKey: queryKeys.availableTrolleys(tenantId, farmId) });
      queryClient.invalidateQueries({
        queryKey: queryKeys.trolleySlots(tenantId, farmId, variables.trolley_id),
      });
      queryClient.invalidateQueries({ queryKey: queryKeys.germinationTrays(tenantId, farmId) });
    },
  });
}

// --- NURSERY-OPS-002B -------------------------------------------------------
// Modern, INDIVIDUAL-SEEDLING-based Germination outcome.

export function useCurrentGerminationOutcomes(farmId: string, batchId: string) {
  const tenantId = useSelectedTenantId();
  return useQuery({
    queryKey: queryKeys.currentGerminationOutcomes(tenantId ?? "", farmId, batchId),
    queryFn: ({ signal }) => api.getCurrentGerminationOutcomes(farmId, batchId, signal),
    staleTime: STALE_DETAIL_MS,
    enabled: Boolean(tenantId) && Boolean(batchId),
  });
}

/** Idempotency key (`client_command_id`) lives in the payload itself, same
 * replay-safe pattern as every other command here. Recording an outcome
 * never changes physical placement/occupancy -- only the Batch's own
 * current-outcome read is invalidated. */
export function useRecordGerminationOutcomes(farmId: string, batchId: string) {
  const tenantId = useSelectedTenantId();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: GerminationOutcomeCommandCreate) => api.recordGerminationOutcomes(farmId, batchId, payload),
    onSuccess: () => {
      if (!tenantId) return;
      queryClient.invalidateQueries({ queryKey: queryKeys.currentGerminationOutcomes(tenantId, farmId, batchId) });
    },
  });
}

// --- NURSERY-OPS-003A -------------------------------------------------------
// Seedling Entry & Placement -- atomic physical Movement + frozen biological
// handoff. No Seedling biological loss/removal here (NURSERY-OPS-003B).

export function useSeedlingCandidateTrays(farmId: string) {
  const tenantId = useSelectedTenantId();
  return useQuery({
    queryKey: queryKeys.seedlingCandidateTrays(tenantId ?? "", farmId),
    queryFn: ({ signal }) => api.listSeedlingCandidateTrays(farmId, signal),
    staleTime: STALE_DETAIL_MS,
    enabled: Boolean(tenantId),
  });
}

export function useAvailableSeedlingTables(farmId: string) {
  const tenantId = useSelectedTenantId();
  return useQuery({
    queryKey: queryKeys.availableSeedlingTables(tenantId ?? "", farmId),
    queryFn: ({ signal }) => api.listAvailableSeedlingTables(farmId, signal),
    staleTime: STALE_DETAIL_MS,
    enabled: Boolean(tenantId),
  });
}

/** Idempotency key (`client_command_id`) lives in the payload itself, same
 * replay-safe pattern as every other command here. A Seedling entry both
 * moves the Tray (affecting Table availability and the Germination page's
 * own tray list) and establishes the frozen handoff (affecting the Seedling
 * tray list) -- all three reads are invalidated. */
export function useRecordSeedlingEntry(farmId: string) {
  const tenantId = useSelectedTenantId();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: SeedlingEntryCreate) => api.recordSeedlingEntry(farmId, payload),
    onSuccess: () => {
      if (!tenantId) return;
      queryClient.invalidateQueries({ queryKey: queryKeys.seedlingCandidateTrays(tenantId, farmId) });
      queryClient.invalidateQueries({ queryKey: queryKeys.availableSeedlingTables(tenantId, farmId) });
      queryClient.invalidateQueries({ queryKey: queryKeys.germinationTrays(tenantId, farmId) });
    },
  });
}

export function useSowings(farmId: string, batchId: string) {
  const tenantId = useSelectedTenantId();
  return useQuery({
    queryKey: queryKeys.sowings(tenantId ?? "", farmId, batchId),
    queryFn: ({ signal }) => api.listSowings(farmId, batchId, signal),
    staleTime: STALE_DETAIL_MS,
    enabled: Boolean(tenantId),
  });
}

/** Like `useCreateGreenhouseSetup`: the idempotency key
 * (`client_command_id`) lives in the payload, set once by the caller
 * before the first submit attempt. On success, invalidates the farm's
 * available-seed-trays list (the sown trays are no longer available) and
 * seed lot list (unaffected in count, but keeps things simple/consistent). */
export function useSowNewBatch(farmId: string) {
  const tenantId = useSelectedTenantId();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: SowNewBatchCreate) => api.sowNewBatch(farmId, payload),
    onSuccess: () => {
      if (!tenantId) return;
      queryClient.invalidateQueries({ queryKey: queryKeys.availableSeedTrays(tenantId, farmId) });
      queryClient.invalidateQueries({ queryKey: queryKeys.operationalSummary(tenantId, farmId, "active") });
      queryClient.invalidateQueries({ queryKey: queryKeys.operationalSummary(tenantId, farmId, "all") });
    },
  });
}

// --- NURSERY-OPS-003B -------------------------------------------------------
// Seedling Biological Dispositions -- immutable, insert-only quantity-
// reducing facts recorded AFTER SeedlingEntry. Distinct from Movement and
// from Observation/Quality holds. Reads reuse SOWING_READ (see api/seedling.py).

export function useSeedlingDispositionReasons(farmId: string) {
  const tenantId = useSelectedTenantId();
  return useQuery({
    queryKey: queryKeys.seedlingDispositionReasons(tenantId ?? "", farmId),
    queryFn: ({ signal }) => api.listSeedlingDispositionReasons(farmId, signal),
    staleTime: STALE_REFERENCE_MS,
    enabled: Boolean(tenantId),
  });
}

export function useSeedlingBiologicalTrays(farmId: string) {
  const tenantId = useSelectedTenantId();
  return useQuery({
    queryKey: queryKeys.seedlingBiologicalTrays(tenantId ?? "", farmId),
    queryFn: ({ signal }) => api.listSeedlingBiologicalTrays(farmId, signal),
    staleTime: STALE_DETAIL_MS,
    enabled: Boolean(tenantId),
  });
}

export function useSeedlingDispositionHistory(farmId: string, seedlingEntryId: string | null) {
  const tenantId = useSelectedTenantId();
  return useQuery({
    queryKey: queryKeys.seedlingDispositionHistory(tenantId ?? "", farmId, seedlingEntryId ?? ""),
    queryFn: ({ signal }) => api.getSeedlingDispositionHistory(farmId, seedlingEntryId as string, signal),
    staleTime: STALE_DETAIL_MS,
    enabled: Boolean(tenantId) && Boolean(seedlingEntryId),
  });
}

/** Idempotency key (`client_command_id`) lives in the payload itself, same
 * replay-safe pattern as every other command here. Recording a disposition
 * only changes the derived current-balance read for this Tray/Seedling
 * entry -- the biological-trays list and that entry's own event history are
 * invalidated; no physical Movement or occupancy read is affected (section
 * 0.5/62 -- disposition is Movement-independent). */
export function useRecordSeedlingDisposition(farmId: string) {
  const tenantId = useSelectedTenantId();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: RecordSeedlingDispositionCreate) => api.recordSeedlingDisposition(farmId, payload),
    onSuccess: (result) => {
      if (!tenantId) return;
      queryClient.invalidateQueries({ queryKey: queryKeys.seedlingBiologicalTrays(tenantId, farmId) });
      queryClient.invalidateQueries({
        queryKey: queryKeys.seedlingDispositionHistory(tenantId, farmId, result.seedling_entry_id),
      });
    },
  });
}

export function useCorrectSeedlingDisposition(farmId: string) {
  const tenantId = useSelectedTenantId();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ eventId, payload }: { eventId: string; payload: CorrectSeedlingDispositionCreate }) =>
      api.correctSeedlingDisposition(farmId, eventId, payload),
    onSuccess: (result) => {
      if (!tenantId) return;
      queryClient.invalidateQueries({ queryKey: queryKeys.seedlingBiologicalTrays(tenantId, farmId) });
      queryClient.invalidateQueries({
        queryKey: queryKeys.seedlingDispositionHistory(tenantId, farmId, result.seedling_entry_id),
      });
    },
  });
}

// --- CARRIER-CONFIG-001 -----------------------------------------------------
// Tenant-scoped, never farm-scoped -- see lib/api/client.ts's own note.

export function useCarrierTypes() {
  const tenantId = useSelectedTenantId();
  return useQuery({
    queryKey: queryKeys.carrierTypes(tenantId ?? ""),
    queryFn: ({ signal }) => api.listCarrierTypes(signal),
    staleTime: STALE_REFERENCE_MS,
    enabled: Boolean(tenantId),
  });
}

export function useCarrierSpecifications() {
  const tenantId = useSelectedTenantId();
  return useQuery({
    queryKey: queryKeys.carrierSpecifications(tenantId ?? ""),
    queryFn: ({ signal }) => api.listCarrierSpecifications(signal),
    staleTime: STALE_LIST_MS,
    enabled: Boolean(tenantId),
  });
}

export function useCreateCarrierSpecification() {
  const tenantId = useSelectedTenantId();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: CarrierSpecificationCreate) => api.createCarrierSpecification(payload),
    onSuccess: () => {
      if (!tenantId) return;
      queryClient.invalidateQueries({ queryKey: queryKeys.carrierSpecifications(tenantId) });
    },
  });
}

export function useUpdateCarrierSpecification() {
  const tenantId = useSelectedTenantId();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ specificationId, payload }: { specificationId: string; payload: CarrierSpecificationUpdate }) =>
      api.updateCarrierSpecification(specificationId, payload),
    onSuccess: (result) => {
      if (!tenantId) return;
      queryClient.invalidateQueries({ queryKey: queryKeys.carrierSpecifications(tenantId) });
      queryClient.invalidateQueries({ queryKey: queryKeys.carrierSpecification(tenantId, result.id) });
    },
  });
}

export function useDeactivateCarrierSpecification() {
  const tenantId = useSelectedTenantId();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (specificationId: string) => api.deactivateCarrierSpecification(specificationId),
    onSuccess: (result) => {
      if (!tenantId) return;
      queryClient.invalidateQueries({ queryKey: queryKeys.carrierSpecifications(tenantId) });
      queryClient.invalidateQueries({ queryKey: queryKeys.carrierSpecification(tenantId, result.id) });
    },
  });
}

export function useReactivateCarrierSpecification() {
  const tenantId = useSelectedTenantId();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (specificationId: string) => api.reactivateCarrierSpecification(specificationId),
    onSuccess: (result) => {
      if (!tenantId) return;
      queryClient.invalidateQueries({ queryKey: queryKeys.carrierSpecifications(tenantId) });
      queryClient.invalidateQueries({ queryKey: queryKeys.carrierSpecification(tenantId, result.id) });
    },
  });
}

// --- NURSERY-OPS-004B.2 -----------------------------------------------------
// InterSalads Transplant operator UI: destination-Plate eligibility read,
// per-Table live occupancy (used only once a Table is selected -- never a
// bulk Table-availability call), and the composite submit itself.

export function useAvailableIntersaladsPlates(farmId: string) {
  const tenantId = useSelectedTenantId();
  return useQuery({
    queryKey: queryKeys.availableIntersaladsPlates(tenantId ?? "", farmId),
    queryFn: ({ signal }) => api.listAvailableIntersaladsPlates(farmId, signal),
    staleTime: STALE_DETAIL_MS,
    enabled: Boolean(tenantId),
  });
}

/** On-demand only, mirrors `useLocationSubtreeOccupancy`'s own `enabled`
 * pattern -- fetched once a specific InterSalads Table is actually
 * selected, never for every Table up front (section 14/15: no bulk
 * Table-availability call). */
export function useLocationOccupants(farmId: string, locationId: string | null) {
  const tenantId = useSelectedTenantId();
  return useQuery({
    queryKey: queryKeys.locationOccupants(tenantId ?? "", farmId, locationId ?? ""),
    queryFn: ({ signal }) => api.getLocationOccupants(farmId, locationId as string, signal),
    staleTime: STALE_DETAIL_MS,
    enabled: Boolean(tenantId) && Boolean(locationId),
  });
}

/** Idempotency key lives in the payload itself, same replay-safe pattern as
 * every other command here. `batchId` is passed per-call (mirrors
 * `useCorrectSeedlingDisposition`'s `{eventId, payload}` shape) since it is
 * only known once the operator has picked a source Tray inside the form,
 * not at hook-creation time. Success changes source availability, Plate
 * eligibility, and the destination Table(s)' occupancy -- all three are
 * invalidated; the composite command performs its own physical Movement, so
 * no separate Movement/Occupancy mutation is ever called from here (section
 * 18/26). */
export function useRecordIntersaladsTransplant(farmId: string) {
  const tenantId = useSelectedTenantId();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ batchId, payload }: { batchId: string; payload: IntersaladsTransplantCreate }) =>
      api.recordIntersaladsTransplant(farmId, batchId, payload),
    onSuccess: (result) => {
      if (!tenantId) return;
      queryClient.invalidateQueries({ queryKey: queryKeys.seedlingBiologicalTrays(tenantId, farmId) });
      queryClient.invalidateQueries({ queryKey: queryKeys.availableIntersaladsPlates(tenantId, farmId) });
      for (const line of result.destination_lines) {
        queryClient.invalidateQueries({
          queryKey: queryKeys.locationOccupants(tenantId, farmId, line.destination_location_id),
        });
      }
    },
    // Section 10 (frozen): a 409 means the state this draft was built
    // against has changed elsewhere (a source, Plate, or Table just got
    // used). Never auto-resubmit -- only refresh the authoritative queries
    // the draft depends on, so the operator's next look at Configure/Review
    // reflects current reality before they try again. The draft's own
    // selections are left untouched here (the form component decides how
    // to react to now-possibly-stale data, e.g. forcing back to Configure).
    onError: (error, variables) => {
      if (!tenantId || !(error instanceof AppError) || error.kind !== "conflict") return;
      queryClient.invalidateQueries({ queryKey: queryKeys.seedlingBiologicalTrays(tenantId, farmId) });
      queryClient.invalidateQueries({ queryKey: queryKeys.availableIntersaladsPlates(tenantId, farmId) });
      const tableIds = new Set(variables.payload.destination_lines.map((d) => d.destination_location_id));
      for (const tableId of tableIds) {
        queryClient.invalidateQueries({ queryKey: queryKeys.locationOccupants(tenantId, farmId, tableId) });
      }
    },
  });
}

// --- NURSERY-OPS-005B --------------------------------------------------------
// Leafy Production Transfer operator UI: source-Plate eligibility read
// (optionally Batch-filtered once a Batch is established), destination-
// Plate eligibility read, per-Table live occupancy (reused unchanged from
// `useLocationOccupants` above), and the composite submit itself. Mirrors
// the InterSalads section immediately above -- same shapes, same
// invalidation discipline, for the sibling composite.

export function useAvailableLeafyProductionSources(farmId: string, batchId?: string) {
  const tenantId = useSelectedTenantId();
  return useQuery({
    queryKey: queryKeys.availableLeafyProductionSources(tenantId ?? "", farmId, batchId ?? ""),
    queryFn: ({ signal }) => api.listAvailableLeafyProductionSources(farmId, batchId, signal),
    staleTime: STALE_DETAIL_MS,
    enabled: Boolean(tenantId),
  });
}

export function useAvailableProductionPlates(farmId: string) {
  const tenantId = useSelectedTenantId();
  return useQuery({
    queryKey: queryKeys.availableProductionPlates(tenantId ?? "", farmId),
    queryFn: ({ signal }) => api.listAvailableProductionPlates(farmId, signal),
    staleTime: STALE_DETAIL_MS,
    enabled: Boolean(tenantId),
  });
}

/** Idempotency key lives in the payload itself, same replay-safe pattern as
 * `useRecordIntersaladsTransplant`. Success changes source availability,
 * Plate eligibility, and the destination Table(s)' occupancy -- the
 * composite command performs its own physical Movement, so no separate
 * Movement/Occupancy mutation is ever called from here. Both the
 * unfiltered and Batch-filtered source-list cache entries are invalidated
 * (the exact Batch id used for this command, since the UI always narrows
 * to it once established). */
export function useRecordLeafyProductionTransfer(farmId: string) {
  const tenantId = useSelectedTenantId();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ batchId, payload }: { batchId: string; payload: LeafyProductionTransferCreate }) =>
      api.recordLeafyProductionTransfer(farmId, batchId, payload),
    onSuccess: (result) => {
      if (!tenantId) return;
      queryClient.invalidateQueries({ queryKey: queryKeys.availableLeafyProductionSources(tenantId, farmId, "") });
      queryClient.invalidateQueries({
        queryKey: queryKeys.availableLeafyProductionSources(tenantId, farmId, result.batch_id),
      });
      queryClient.invalidateQueries({ queryKey: queryKeys.availableProductionPlates(tenantId, farmId) });
      for (const line of result.destination_lines) {
        queryClient.invalidateQueries({
          queryKey: queryKeys.locationOccupants(tenantId, farmId, line.destination_location_id),
        });
      }
    },
    onError: (error, variables) => {
      if (!tenantId || !(error instanceof AppError) || error.kind !== "conflict") return;
      queryClient.invalidateQueries({ queryKey: queryKeys.availableLeafyProductionSources(tenantId, farmId, "") });
      queryClient.invalidateQueries({ queryKey: queryKeys.availableLeafyProductionSources(tenantId, farmId, variables.batchId) });
      queryClient.invalidateQueries({ queryKey: queryKeys.availableProductionPlates(tenantId, farmId) });
      const tableIds = new Set(variables.payload.destination_lines.map((d) => d.destination_location_id));
      for (const tableId of tableIds) {
        queryClient.invalidateQueries({ queryKey: queryKeys.locationOccupants(tenantId, farmId, tableId) });
      }
    },
  });
}

// --- LEAFY-OPS-001 -------------------------------------------------------------
// Production Biological Disposition: Active Production Plates / Plant Loss
// History workspace reads, and the record/correct commands. Mirrors the
// NURSERY-OPS-005B section's own invalidation discipline exactly.

export function useActiveProductionPlates(farmId: string, batchId?: string) {
  const tenantId = useSelectedTenantId();
  return useQuery({
    queryKey: queryKeys.activeProductionPlates(tenantId ?? "", farmId, batchId ?? ""),
    queryFn: ({ signal }) => api.listActiveProductionPlates(farmId, batchId, signal),
    staleTime: STALE_DETAIL_MS,
    enabled: Boolean(tenantId),
  });
}

export function useProductionDispositionHistory(
  farmId: string, params: { batchCarrierAssignmentId?: string; batchId?: string } = {},
) {
  const tenantId = useSelectedTenantId();
  return useQuery({
    queryKey: queryKeys.productionDispositionHistory(
      tenantId ?? "", farmId, params.batchCarrierAssignmentId ?? "", params.batchId ?? "",
    ),
    queryFn: ({ signal }) => api.listProductionDispositionHistory(farmId, params, signal),
    staleTime: STALE_DETAIL_MS,
    enabled: Boolean(tenantId),
  });
}

function _invalidateProductionDisposition(
  queryClient: ReturnType<typeof useQueryClient>, tenantId: string, farmId: string,
) {
  queryClient.invalidateQueries({ queryKey: queryKeys.activeProductionPlates(tenantId, farmId, "") });
  queryClient.invalidateQueries({ queryKey: queryKeys.productionDispositionHistory(tenantId, farmId, "", "") });
}

export function useRecordProductionDisposition(farmId: string) {
  const tenantId = useSelectedTenantId();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: RecordProductionDispositionCreate) => api.recordProductionDisposition(farmId, payload),
    onSuccess: () => {
      if (!tenantId) return;
      _invalidateProductionDisposition(queryClient, tenantId, farmId);
    },
    onError: (error) => {
      if (!tenantId || !(error instanceof AppError) || error.kind !== "conflict") return;
      _invalidateProductionDisposition(queryClient, tenantId, farmId);
    },
  });
}

export function useCorrectProductionDisposition(farmId: string) {
  const tenantId = useSelectedTenantId();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ eventId, payload }: { eventId: string; payload: CorrectProductionDispositionCreate }) =>
      api.correctProductionDisposition(farmId, eventId, payload),
    onSuccess: () => {
      if (!tenantId) return;
      _invalidateProductionDisposition(queryClient, tenantId, farmId);
    },
    onError: (error) => {
      if (!tenantId || !(error instanceof AppError) || error.kind !== "conflict") return;
      _invalidateProductionDisposition(queryClient, tenantId, farmId);
    },
  });
}

// --- HARVEST-OPS-001 SLICE 2 -----------------------------------------------------
// Harvestable Plates / Harvest history reads, and the record/correct
// commands. Mirrors LEAFY-OPS-001's own invalidation discipline exactly --
// refetch-then-force-back-to-editable-step is the component's job (see
// LeafyHarvestForm/CorrectHarvestForm), this layer only keeps the cache honest.

export function useHarvestablePlates(farmId: string, batchId?: string) {
  const tenantId = useSelectedTenantId();
  return useQuery({
    queryKey: queryKeys.harvestablePlates(tenantId ?? "", farmId, batchId ?? ""),
    queryFn: ({ signal }) => api.listHarvestablePlates(farmId, batchId, signal),
    staleTime: STALE_DETAIL_MS,
    enabled: Boolean(tenantId),
  });
}

export function useLeafyHarvests(farmId: string, batchId?: string) {
  const tenantId = useSelectedTenantId();
  return useQuery({
    queryKey: queryKeys.leafyHarvests(tenantId ?? "", farmId, batchId ?? ""),
    queryFn: ({ signal }) => api.listLeafyHarvests(farmId, batchId, signal),
    staleTime: STALE_DETAIL_MS,
    enabled: Boolean(tenantId),
  });
}

export function useLeafyHarvest(farmId: string, harvestEventId: string | null) {
  const tenantId = useSelectedTenantId();
  return useQuery({
    queryKey: queryKeys.leafyHarvest(tenantId ?? "", farmId, harvestEventId ?? ""),
    queryFn: ({ signal }) => api.getLeafyHarvest(farmId, harvestEventId as string, signal),
    staleTime: STALE_DETAIL_MS,
    enabled: Boolean(tenantId) && Boolean(harvestEventId),
  });
}

function _invalidateLeafyHarvest(queryClient: ReturnType<typeof useQueryClient>, tenantId: string, farmId: string) {
  queryClient.invalidateQueries({ queryKey: queryKeys.harvestablePlates(tenantId, farmId, "") });
  queryClient.invalidateQueries({ queryKey: queryKeys.leafyHarvests(tenantId, farmId, "") });
  queryClient.invalidateQueries({
    queryKey: ["tenant", tenantId, "farms", farmId, "leafy-production", "harvests", "detail"],
  });
}

export function useRecordLeafyHarvest(farmId: string) {
  const tenantId = useSelectedTenantId();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: RecordLeafyHarvestCreate) => api.recordLeafyHarvest(farmId, payload),
    onSuccess: () => {
      if (!tenantId) return;
      _invalidateLeafyHarvest(queryClient, tenantId, farmId);
    },
    onError: (error) => {
      if (!tenantId || !(error instanceof AppError) || error.kind !== "conflict") return;
      _invalidateLeafyHarvest(queryClient, tenantId, farmId);
    },
  });
}

// --- POSTHARVEST-OPS-001G ---------------------------------------------------
// Processing & Packing UI: Grading (Harvested Produce Lot -> Graded Produce
// Lots), Graded Produce Lots read access, Packing (Graded Produce Lots ->
// Finished Goods), Finished Goods read access + placement, and a farm-wide
// Recall Cases read used only to flag "under an open recall" on a lot.

export function useHarvestedProduceLots(farmId: string) {
  const tenantId = useSelectedTenantId();
  return useQuery({
    queryKey: queryKeys.harvestedProduceLots(tenantId ?? "", farmId),
    queryFn: ({ signal }) => api.listHarvestedProduceLots(farmId, signal),
    staleTime: STALE_LIST_MS,
    enabled: Boolean(tenantId),
  });
}

/** On-demand only (mirrors `useLocationSubtreeOccupancy`) -- fetched once a
 * specific Harvested Produce Lot is selected as a Grading source, never for
 * every row in the list up front (no bulk balance endpoint exists). */
export function useHarvestedProduceLotBalance(farmId: string, produceLotId: string | null) {
  const tenantId = useSelectedTenantId();
  return useQuery({
    queryKey: queryKeys.harvestedProduceLotBalance(tenantId ?? "", farmId, produceLotId ?? ""),
    queryFn: ({ signal }) => api.getHarvestedProduceLotBalance(farmId, produceLotId as string, signal),
    staleTime: STALE_DETAIL_MS,
    enabled: Boolean(tenantId) && Boolean(produceLotId),
  });
}

/** Unfiltered, tenant-wide -- the "" cache slot of `queryKeys.gradeDefinitions`
 * doubles as the "all Definitions" entry (mirrors NURSERY-OPS-005B's own
 * "" = unfiltered convention). Backs `useGradeVersionLabelMap` below. */
export function useAllGradeDefinitions() {
  const tenantId = useSelectedTenantId();
  return useQuery({
    queryKey: queryKeys.gradeDefinitions(tenantId ?? "", ""),
    queryFn: ({ signal }) => api.listGradeDefinitions(undefined, signal),
    staleTime: STALE_REFERENCE_MS,
    enabled: Boolean(tenantId),
  });
}

/** Builds `{ [gradeDefinitionVersionId]: "Definition Name vN" }` across
 * every Grade Definition in the tenant. There is no "get a Version by id
 * alone" endpoint -- Versions are nested under their Definition -- so any
 * screen that needs a human label for a `grade_definition_version_id`
 * (Graded Produce Lot rows, Grading history) resolves it via this one map
 * rather than a per-row lookup. Tenant reference data (long staleTime); an
 * acceptable one-time cost for a tenant's whole Grade Definition catalog. */
export function useGradeVersionLabelMap(): { labels: Record<string, string>; isLoading: boolean } {
  const tenantId = useSelectedTenantId();
  const definitionsQuery = useAllGradeDefinitions();
  const definitions = definitionsQuery.data ?? [];
  const versionQueries = useQueries({
    queries: definitions.map((d) => ({
      queryKey: queryKeys.gradeDefinitionVersions(tenantId ?? "", d.id, ""),
      queryFn: ({ signal }: { signal: AbortSignal }) => api.listGradeDefinitionVersions(d.id, undefined, signal),
      staleTime: STALE_REFERENCE_MS,
      enabled: Boolean(tenantId),
    })),
  });
  const labels: Record<string, string> = {};
  definitions.forEach((d, i) => {
    for (const v of versionQueries[i]?.data ?? []) labels[v.id] = `${d.name} v${v.version_number}`;
  });
  return { labels, isLoading: definitionsQuery.isLoading || versionQueries.some((q) => q.isLoading) };
}

/** Same rationale as `useAllGradeDefinitions`, for Pack Specifications. */
export function useAllPackSpecifications() {
  const tenantId = useSelectedTenantId();
  return useQuery({
    queryKey: queryKeys.packSpecifications(tenantId ?? "", ""),
    queryFn: ({ signal }) => api.listPackSpecifications(undefined, signal),
    staleTime: STALE_REFERENCE_MS,
    enabled: Boolean(tenantId),
  });
}

/** Same rationale as `useGradeVersionLabelMap`, for
 * `pack_specification_version_id`. */
export function usePackVersionLabelMap(): { labels: Record<string, string>; isLoading: boolean } {
  const tenantId = useSelectedTenantId();
  const specsQuery = useAllPackSpecifications();
  const specs = specsQuery.data ?? [];
  const versionQueries = useQueries({
    queries: specs.map((s) => ({
      queryKey: queryKeys.packSpecificationVersions(tenantId ?? "", s.id, ""),
      queryFn: ({ signal }: { signal: AbortSignal }) => api.listPackSpecificationVersions(s.id, undefined, signal),
      staleTime: STALE_REFERENCE_MS,
      enabled: Boolean(tenantId),
    })),
  });
  const labels: Record<string, string> = {};
  specs.forEach((s, i) => {
    for (const v of versionQueries[i]?.data ?? []) labels[v.id] = `${s.name} v${v.version_number}`;
  });
  return { labels, isLoading: specsQuery.isLoading || versionQueries.some((q) => q.isLoading) };
}

export function useGradeDefinitions(cropId: string | undefined) {
  const tenantId = useSelectedTenantId();
  return useQuery({
    queryKey: queryKeys.gradeDefinitions(tenantId ?? "", cropId ?? ""),
    queryFn: ({ signal }) => api.listGradeDefinitions(cropId, signal),
    staleTime: STALE_REFERENCE_MS,
    enabled: Boolean(tenantId) && Boolean(cropId),
  });
}

/** PRE-COMMIT CORRECTION: fetches every Version regardless of lifecycle
 * status (no `status` filter) -- a historically-valid RETIRED Version must
 * remain selectable for a backdated transaction, so status alone can never
 * be the filter. Callers narrow to what's selectable for a given
 * `effective_time` via `selectableVersionsAt` (`lib/format/
 * versionLifecycle.ts`), not via this query. Same "" cache slot as
 * `useGradeVersionLabelMap`'s own all-versions fetch, so the two never
 * duplicate the request. */
export function useGradeDefinitionVersions(gradeDefinitionId: string | null) {
  const tenantId = useSelectedTenantId();
  return useQuery({
    queryKey: queryKeys.gradeDefinitionVersions(tenantId ?? "", gradeDefinitionId ?? "", ""),
    queryFn: ({ signal }) => api.listGradeDefinitionVersions(gradeDefinitionId as string, undefined, signal),
    staleTime: STALE_REFERENCE_MS,
    enabled: Boolean(tenantId) && Boolean(gradeDefinitionId),
  });
}

export function useGradingEvents(farmId: string, sourceHarvestedProduceLotId?: string) {
  const tenantId = useSelectedTenantId();
  return useQuery({
    queryKey: queryKeys.gradingEvents(tenantId ?? "", farmId, sourceHarvestedProduceLotId ?? ""),
    queryFn: ({ signal }) => api.listGradingEvents(farmId, sourceHarvestedProduceLotId, signal),
    staleTime: STALE_LIST_MS,
    enabled: Boolean(tenantId),
  });
}

/** On-demand only -- used to resolve a Graded Produce Lot's source
 * Harvested Produce Lot, since a GPL only carries `grading_event_id`, not
 * the source Lot id/code directly (see the Grading Event's own
 * `source_harvested_produce_lot_id`/`source_produce_lot_code`). */
export function useGradingEvent(farmId: string, gradingEventId: string | null) {
  const tenantId = useSelectedTenantId();
  return useQuery({
    queryKey: queryKeys.gradingEvent(tenantId ?? "", farmId, gradingEventId ?? ""),
    queryFn: ({ signal }) => api.getGradingEvent(farmId, gradingEventId as string, signal),
    staleTime: STALE_DETAIL_MS,
    enabled: Boolean(tenantId) && Boolean(gradingEventId),
  });
}

export function useGradedProduceLots(
  farmId: string,
  params: { cropId?: string; varietyId?: string; gradeDefinitionVersionId?: string } = {},
) {
  const tenantId = useSelectedTenantId();
  const filterKey = JSON.stringify(params);
  return useQuery({
    queryKey: queryKeys.gradedProduceLots(tenantId ?? "", farmId, filterKey),
    queryFn: ({ signal }) => api.listGradedProduceLots(farmId, params, signal),
    staleTime: STALE_LIST_MS,
    enabled: Boolean(tenantId),
  });
}

export function useGradedProduceLot(farmId: string, gradedProduceLotId: string | null) {
  const tenantId = useSelectedTenantId();
  return useQuery({
    queryKey: queryKeys.gradedProduceLot(tenantId ?? "", farmId, gradedProduceLotId ?? ""),
    queryFn: ({ signal }) => api.getGradedProduceLot(farmId, gradedProduceLotId as string, signal),
    staleTime: STALE_DETAIL_MS,
    enabled: Boolean(tenantId) && Boolean(gradedProduceLotId),
  });
}

export function useGradedProduceLotLedger(farmId: string, gradedProduceLotId: string | null) {
  const tenantId = useSelectedTenantId();
  return useQuery({
    queryKey: queryKeys.gradedProduceLotLedger(tenantId ?? "", farmId, gradedProduceLotId ?? ""),
    queryFn: ({ signal }) => api.getGradedProduceLotLedger(farmId, gradedProduceLotId as string, signal),
    staleTime: STALE_DETAIL_MS,
    enabled: Boolean(tenantId) && Boolean(gradedProduceLotId),
  });
}

/** On-demand per Lot -- used both for a single Lot's detail page and (via
 * `useQueries` in the calling component) for the Graded Produce Lots list
 * and the Packing input picker, where seeing "available weight/count" per
 * row is operationally required and no bulk balance endpoint exists. */
export function useGradedProduceLotBalance(farmId: string, gradedProduceLotId: string | null) {
  const tenantId = useSelectedTenantId();
  return useQuery({
    queryKey: queryKeys.gradedProduceLotBalance(tenantId ?? "", farmId, gradedProduceLotId ?? ""),
    queryFn: ({ signal }) => api.getGradedProduceLotBalance(farmId, gradedProduceLotId as string, signal),
    staleTime: STALE_DETAIL_MS,
    enabled: Boolean(tenantId) && Boolean(gradedProduceLotId),
  });
}

function _invalidateGrading(queryClient: ReturnType<typeof useQueryClient>, tenantId: string, farmId: string) {
  queryClient.invalidateQueries({ queryKey: queryKeys.harvestedProduceLots(tenantId, farmId) });
  queryClient.invalidateQueries({ queryKey: queryKeys.gradingEvents(tenantId, farmId, "") });
  // Prefix-only (no `filterKey`) so every crop/variety-filtered cache entry
  // is invalidated too, not just the unfiltered one.
  queryClient.invalidateQueries({ queryKey: ["tenant", tenantId, "farms", farmId, "graded-produce-lots"] });
}

export function useRecordGrading(farmId: string) {
  const tenantId = useSelectedTenantId();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: GradingEventCreate) => api.recordGrading(farmId, payload),
    onSuccess: (result) => {
      if (!tenantId) return;
      _invalidateGrading(queryClient, tenantId, farmId);
      queryClient.invalidateQueries({
        queryKey: queryKeys.harvestedProduceLotBalance(tenantId, farmId, result.source_harvested_produce_lot_id),
      });
    },
    onError: (error) => {
      if (!tenantId || !(error instanceof AppError) || error.kind !== "conflict") return;
      _invalidateGrading(queryClient, tenantId, farmId);
    },
  });
}

/** Whether the target GradingEvent has already been reversed -- 404 (never
 * reversed) is a normal, expected outcome, not an error state. */
export function useGradingReversalEvent(farmId: string, gradingEventId: string | null) {
  const tenantId = useSelectedTenantId();
  return useQuery({
    queryKey: queryKeys.gradingReversalEvent(tenantId ?? "", farmId, gradingEventId ?? ""),
    queryFn: async ({ signal }) => {
      try {
        return await api.getGradingReversalEvent(farmId, gradingEventId as string, signal);
      } catch (error) {
        if (error instanceof AppError && error.kind === "not_found") return null;
        throw error;
      }
    },
    staleTime: STALE_DETAIL_MS,
    enabled: Boolean(tenantId) && Boolean(gradingEventId),
  });
}

/** POSTHARVEST-OPS-001H: whole-event reversal only -- never a field-by-field
 * correction. `sourceHarvestedProduceLotId` is threaded through purely for
 * cache invalidation (the reversal response itself does not carry it). */
export function useReverseGradingEvent(farmId: string) {
  const tenantId = useSelectedTenantId();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (variables: {
      gradingEventId: string;
      sourceHarvestedProduceLotId: string;
      payload: GradingReversalEventCreate;
    }) => api.reverseGradingEvent(farmId, variables.gradingEventId, variables.payload),
    onSuccess: (result, variables) => {
      if (!tenantId) return;
      _invalidateGrading(queryClient, tenantId, farmId);
      queryClient.invalidateQueries({
        queryKey: queryKeys.gradingReversalEvent(tenantId, farmId, variables.gradingEventId),
      });
      queryClient.invalidateQueries({
        queryKey: queryKeys.harvestedProduceLotBalance(tenantId, farmId, variables.sourceHarvestedProduceLotId),
      });
      for (const output of result.outputs) {
        queryClient.invalidateQueries({
          queryKey: queryKeys.gradedProduceLotBalance(tenantId, farmId, output.graded_produce_lot_id),
        });
      }
    },
    onError: (error, variables) => {
      if (!tenantId || !(error instanceof AppError) || error.kind !== "conflict") return;
      queryClient.invalidateQueries({
        queryKey: queryKeys.gradingReversalEvent(tenantId, farmId, variables.gradingEventId),
      });
    },
  });
}

export function usePackSpecifications(cropId: string | undefined) {
  const tenantId = useSelectedTenantId();
  return useQuery({
    queryKey: queryKeys.packSpecifications(tenantId ?? "", cropId ?? ""),
    queryFn: ({ signal }) => api.listPackSpecifications(cropId, signal),
    staleTime: STALE_REFERENCE_MS,
    enabled: Boolean(tenantId) && Boolean(cropId),
  });
}

/** Same rationale as `useGradeDefinitionVersions` -- fetches every Version
 * regardless of lifecycle status; callers narrow via `selectableVersionsAt`. */
export function usePackSpecificationVersions(packSpecificationId: string | null) {
  const tenantId = useSelectedTenantId();
  return useQuery({
    queryKey: queryKeys.packSpecificationVersions(tenantId ?? "", packSpecificationId ?? "", ""),
    queryFn: ({ signal }) => api.listPackSpecificationVersions(packSpecificationId as string, undefined, signal),
    staleTime: STALE_REFERENCE_MS,
    enabled: Boolean(tenantId) && Boolean(packSpecificationId),
  });
}

export function usePackingEvents(farmId: string) {
  const tenantId = useSelectedTenantId();
  return useQuery({
    queryKey: queryKeys.packingEvents(tenantId ?? "", farmId),
    queryFn: ({ signal }) => api.listPackingEvents(farmId, signal),
    staleTime: STALE_LIST_MS,
    enabled: Boolean(tenantId),
  });
}

export function useFinishedGoodsLots(farmId: string) {
  const tenantId = useSelectedTenantId();
  return useQuery({
    queryKey: queryKeys.finishedGoodsLots(tenantId ?? "", farmId),
    queryFn: ({ signal }) => api.listFinishedGoodsLots(farmId, signal),
    staleTime: STALE_LIST_MS,
    enabled: Boolean(tenantId),
  });
}

export function useFinishedGoodsLot(farmId: string, finishedGoodsLotId: string | null) {
  const tenantId = useSelectedTenantId();
  return useQuery({
    queryKey: queryKeys.finishedGoodsLot(tenantId ?? "", farmId, finishedGoodsLotId ?? ""),
    queryFn: ({ signal }) => api.getFinishedGoodsLot(farmId, finishedGoodsLotId as string, signal),
    staleTime: STALE_DETAIL_MS,
    enabled: Boolean(tenantId) && Boolean(finishedGoodsLotId),
  });
}

export function useFinishedGoodsLedger(farmId: string, finishedGoodsLotId: string | null) {
  const tenantId = useSelectedTenantId();
  return useQuery({
    queryKey: queryKeys.finishedGoodsLedger(tenantId ?? "", farmId, finishedGoodsLotId ?? ""),
    queryFn: ({ signal }) => api.getFinishedGoodsLedger(farmId, finishedGoodsLotId as string, signal),
    staleTime: STALE_DETAIL_MS,
    enabled: Boolean(tenantId) && Boolean(finishedGoodsLotId),
  });
}

/** On-demand per Lot, same rationale as `useGradedProduceLotBalance`. */
export function useFinishedGoodsBalance(farmId: string, finishedGoodsLotId: string | null) {
  const tenantId = useSelectedTenantId();
  return useQuery({
    queryKey: queryKeys.finishedGoodsBalance(tenantId ?? "", farmId, finishedGoodsLotId ?? ""),
    queryFn: ({ signal }) => api.getFinishedGoodsBalance(farmId, finishedGoodsLotId as string, signal),
    staleTime: STALE_DETAIL_MS,
    enabled: Boolean(tenantId) && Boolean(finishedGoodsLotId),
  });
}

export function useFinishedGoodsPlacement(farmId: string, finishedGoodsLotId: string | null) {
  const tenantId = useSelectedTenantId();
  return useQuery({
    queryKey: queryKeys.finishedGoodsPlacement(tenantId ?? "", farmId, finishedGoodsLotId ?? ""),
    queryFn: ({ signal }) => api.getFinishedGoodsPlacement(farmId, finishedGoodsLotId as string, signal),
    staleTime: STALE_DETAIL_MS,
    enabled: Boolean(tenantId) && Boolean(finishedGoodsLotId),
  });
}

function _invalidatePacking(queryClient: ReturnType<typeof useQueryClient>, tenantId: string, farmId: string) {
  queryClient.invalidateQueries({ queryKey: ["tenant", tenantId, "farms", farmId, "graded-produce-lots"] });
  queryClient.invalidateQueries({ queryKey: queryKeys.packingEvents(tenantId, farmId) });
  queryClient.invalidateQueries({ queryKey: queryKeys.finishedGoodsLots(tenantId, farmId) });
}

export function useRecordPacking(farmId: string) {
  const tenantId = useSelectedTenantId();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: PackingEventCreate) => api.recordPacking(farmId, payload),
    onSuccess: (result) => {
      if (!tenantId) return;
      _invalidatePacking(queryClient, tenantId, farmId);
      for (const line of result.input_lines) {
        queryClient.invalidateQueries({
          queryKey: queryKeys.gradedProduceLotBalance(tenantId, farmId, line.graded_produce_lot_id),
        });
      }
    },
    onError: (error) => {
      if (!tenantId || !(error instanceof AppError) || error.kind !== "conflict") return;
      _invalidatePacking(queryClient, tenantId, farmId);
    },
  });
}

/** Whether the target PackingEvent has already been reversed -- 404 (never
 * reversed) is a normal, expected outcome, not an error state. */
export function usePackingReversalEvent(farmId: string, packingEventId: string | null) {
  const tenantId = useSelectedTenantId();
  return useQuery({
    queryKey: queryKeys.packingReversalEvent(tenantId ?? "", farmId, packingEventId ?? ""),
    queryFn: async ({ signal }) => {
      try {
        return await api.getPackingReversalEvent(farmId, packingEventId as string, signal);
      } catch (error) {
        if (error instanceof AppError && error.kind === "not_found") return null;
        throw error;
      }
    },
    staleTime: STALE_DETAIL_MS,
    enabled: Boolean(tenantId) && Boolean(packingEventId),
  });
}

/** POSTHARVEST-OPS-001H: whole-event reversal only -- never a field-by-field
 * correction. `finishedGoodsLotId` is threaded through purely for cache
 * invalidation (the reversal response itself does not carry it). */
export function useReversePackingEvent(farmId: string) {
  const tenantId = useSelectedTenantId();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (variables: {
      packingEventId: string;
      finishedGoodsLotId: string;
      payload: PackingReversalEventCreate;
    }) => api.reversePackingEvent(farmId, variables.packingEventId, variables.payload),
    onSuccess: (result, variables) => {
      if (!tenantId) return;
      _invalidatePacking(queryClient, tenantId, farmId);
      queryClient.invalidateQueries({
        queryKey: queryKeys.packingReversalEvent(tenantId, farmId, variables.packingEventId),
      });
      queryClient.invalidateQueries({
        queryKey: queryKeys.finishedGoodsBalance(tenantId, farmId, variables.finishedGoodsLotId),
      });
      for (const input of result.inputs) {
        queryClient.invalidateQueries({
          queryKey: queryKeys.gradedProduceLotBalance(tenantId, farmId, input.graded_produce_lot_id),
        });
      }
    },
    onError: (error, variables) => {
      if (!tenantId || !(error instanceof AppError) || error.kind !== "conflict") return;
      queryClient.invalidateQueries({
        queryKey: queryKeys.packingReversalEvent(tenantId, farmId, variables.packingEventId),
      });
    },
  });
}

/** Farm-wide, read-only -- used only to flag "under an open recall" on a
 * Graded Produce Lot / Finished Goods Lot row (no dedicated per-lot recall
 * flag endpoint exists; see `lib/api/client.ts`'s own note). */
export function useRecallCases(farmId: string) {
  const tenantId = useSelectedTenantId();
  return useQuery({
    queryKey: queryKeys.recallCases(tenantId ?? "", farmId),
    queryFn: ({ signal }) => api.listRecallCases(farmId, signal),
    staleTime: STALE_LIST_MS,
    enabled: Boolean(tenantId),
  });
}

export function useRecallCase(farmId: string, recallCaseId: string | null) {
  const tenantId = useSelectedTenantId();
  return useQuery({
    queryKey: queryKeys.recallCase(tenantId ?? "", farmId, recallCaseId ?? ""),
    queryFn: ({ signal }) => api.getRecallCase(farmId, recallCaseId as string, signal),
    staleTime: STALE_DETAIL_MS,
    enabled: Boolean(tenantId) && Boolean(recallCaseId),
  });
}

function _invalidateRecallCases(queryClient: ReturnType<typeof useQueryClient>, tenantId: string, farmId: string) {
  queryClient.invalidateQueries({ queryKey: queryKeys.recallCases(tenantId, farmId) });
}

export function useOpenRecallCase(farmId: string) {
  const tenantId = useSelectedTenantId();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: RecallCaseCreate) => api.openRecallCase(farmId, payload),
    onSuccess: () => {
      if (!tenantId) return;
      _invalidateRecallCases(queryClient, tenantId, farmId);
    },
  });
}

export function useCloseRecallCase(farmId: string) {
  const tenantId = useSelectedTenantId();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (variables: { recallCaseId: string; payload: RecallCaseClose }) =>
      api.closeRecallCase(farmId, variables.recallCaseId, variables.payload),
    onSuccess: (_result, variables) => {
      if (!tenantId) return;
      _invalidateRecallCases(queryClient, tenantId, farmId);
      queryClient.invalidateQueries({ queryKey: queryKeys.recallCase(tenantId, farmId, variables.recallCaseId) });
    },
  });
}

// --- PILOT-READY-001: Cold Storage -------------------------------------

export function useFinishedGoodsStorageMovements(farmId: string, finishedGoodsLotId: string | null) {
  const tenantId = useSelectedTenantId();
  return useQuery({
    queryKey: queryKeys.finishedGoodsStorageMovements(tenantId ?? "", farmId, finishedGoodsLotId ?? ""),
    queryFn: ({ signal }) => api.listFinishedGoodsStorageMovements(farmId, finishedGoodsLotId as string, signal),
    staleTime: STALE_DETAIL_MS,
    enabled: Boolean(tenantId) && Boolean(finishedGoodsLotId),
  });
}

export function useRecordFinishedGoodsStorageMovement(farmId: string) {
  const tenantId = useSelectedTenantId();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: FinishedGoodsStorageMovementCreate) => api.recordFinishedGoodsStorageMovement(farmId, payload),
    onSuccess: (result) => {
      if (!tenantId) return;
      queryClient.invalidateQueries({
        queryKey: queryKeys.finishedGoodsPlacement(tenantId, farmId, result.finished_goods_lot_id),
      });
      queryClient.invalidateQueries({
        queryKey: queryKeys.finishedGoodsStorageMovements(tenantId, farmId, result.finished_goods_lot_id),
      });
    },
  });
}

// --- PILOT-READY-001: Dispatch -------------------------------------------

export function useDispatchEvents(farmId: string) {
  const tenantId = useSelectedTenantId();
  return useQuery({
    queryKey: queryKeys.dispatches(tenantId ?? "", farmId),
    queryFn: ({ signal }) => api.listDispatchEvents(farmId, signal),
    staleTime: STALE_LIST_MS,
    enabled: Boolean(tenantId),
  });
}

export function useRecordDispatch(farmId: string) {
  const tenantId = useSelectedTenantId();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: DispatchEventCreate) => api.recordDispatch(farmId, payload),
    onSuccess: (result) => {
      if (!tenantId) return;
      queryClient.invalidateQueries({ queryKey: queryKeys.dispatches(tenantId, farmId) });
      for (const line of result.lines) {
        queryClient.invalidateQueries({
          queryKey: queryKeys.finishedGoodsPlacement(tenantId, farmId, line.finished_goods_lot_id),
        });
        queryClient.invalidateQueries({
          queryKey: queryKeys.finishedGoodsBalance(tenantId, farmId, line.finished_goods_lot_id),
        });
      }
    },
  });
}

export function useCorrectLeafyHarvestSourceLine(farmId: string) {
  const tenantId = useSelectedTenantId();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (
      { harvestEventId, harvestSourceLineId, payload }: {
        harvestEventId: string; harvestSourceLineId: string; payload: CorrectLeafyHarvestSourceLineCreate;
      },
    ) => api.correctLeafyHarvestSourceLine(farmId, harvestEventId, harvestSourceLineId, payload),
    onSuccess: () => {
      if (!tenantId) return;
      _invalidateLeafyHarvest(queryClient, tenantId, farmId);
    },
    onError: (error) => {
      if (!tenantId || !(error instanceof AppError) || error.kind !== "conflict") return;
      _invalidateLeafyHarvest(queryClient, tenantId, farmId);
    },
  });
}
