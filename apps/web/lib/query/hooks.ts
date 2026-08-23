"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import * as api from "@/lib/api/client";
import type {
  CarrierSpecificationCreate,
  CarrierSpecificationUpdate,
  CorrectSeedlingDispositionCreate,
  GerminationOutcomeCommandCreate,
  GreenhouseSetupCreate,
  IntersaladsTransplantCreate,
  PlaceTrayCreate,
  PlaceTrolleyCreate,
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
