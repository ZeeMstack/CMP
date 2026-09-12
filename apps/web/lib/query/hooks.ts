"use client";

import { useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";

import * as api from "@/lib/api/client";
import type {
  CarrierBulkCreate,
  CarrierCreate,
  CarrierSpecificationCreate,
  CarrierSpecificationUpdate,
  CorrectLeafyHarvestSourceLineCreate,
  CorrectVinesHarvestSourceLineCreate,
  CorrectProductionDispositionCreate,
  CorrectSeedlingDispositionCreate,
  CropCreate,
  DispatchEventCreate,
  FarmCreate,
  FinishedGoodsStorageMovementCreate,
  GerminationOutcomeCommandCreate,
  GoodsReceiptCreate,
  GradeDefinitionCreate,
  GradeDefinitionVersionActivate,
  GradeDefinitionVersionCreate,
  GradeDefinitionVersionRetire,
  GradingEventCreate,
  GradingReversalEventCreate,
  GreenhouseSetupCreate,
  IntersaladsTransplantCreate,
  IntervinesTransplantCreate,
  InventoryCategoryCreate,
  InventoryCategoryDeactivate,
  InventoryCategoryReactivate,
  InventoryCategoryUpdate,
  InventoryItemCreate,
  InventoryItemDeactivate,
  InventoryItemPackagingCreate,
  InventoryItemPackagingDeactivate,
  InventoryItemPackagingReactivate,
  InventoryItemPackagingUpdate,
  InventoryItemReactivate,
  InventoryItemSeedProfileCreate,
  InventoryItemSeedProfileRemove,
  InventoryItemSeedProfileUpdate,
  InventoryItemUpdate,
  InventoryIssueCreate,
  InventoryConsumptionCreate,
  InventoryPutawayCreate,
  InventoryReservationCreate,
  InventoryReservationReleaseCreate,
  InventoryReturnCreate,
  InventoryScrapCreate,
  InventoryStorageTransferCreate,
  LeafyProductionTransferCreate,
  LocationBulkChildrenCreate,
  LocationCreate,
  LocationDeactivate,
  LocationReactivate,
  LocationUpdate,
  MovementCreate,
  MembershipCreate,
  MembershipRoleChange,
  ObservationEventCreate,
  PackagingUnitCreate,
  PackagingUnitRetire,
  PackingEventCreate,
  PackingReversalEventCreate,
  PackSpecificationCreate,
  PackSpecificationVersionActivate,
  PackSpecificationVersionCreate,
  PackSpecificationVersionRetire,
  PlaceTrayCreate,
  PlaceTrolleyCreate,
  PlatformTenantOnboardingCreate,
  ProductionRequirementCreate,
  ProductionRequirementStatusCommand,
  ProductionRequirementUpdate,
  ProductionSystemCreate,
  QualityDispositionCorrectionCreate,
  QualityDispositionCreate,
  QualityPartialCorrectionCreate,
  QualityPartialDispositionCreate,
  RecallCaseClose,
  RecallCaseCreate,
  RecordLeafyHarvestCreate,
  RecordVinesHarvestCreate,
  RecordProductionDispositionCreate,
  RecordSeedlingDispositionCreate,
  SeedingProgramLineCreate,
  SeedingProgramLineStatusCommand,
  SeedingProgramLineUpdate,
  SeedlingEntryCreate,
  SeedLotCreate,
  SowNewBatchCreate,
  VarietyCreate,
  VinesProductionTransferCreate,
  RecordVinesGrowCubeDispositionCreate,
  CorrectVinesGrowCubeDispositionCreate,
  WorkflowCreate,
  WorkflowStageCreate,
  WorkflowTransitionCreate,
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

/** UX-IA-001: the selected Tenant's display name, for scope-communication
 * copy ("Shared across <Tenant name>") -- reuses the same
 * `useAuthBootstrap` data AppShell/StandaloneShell already load, no new
 * API call. `undefined` before bootstrap resolves. */
export function useSelectedTenantName(): string | undefined {
  const { bootstrap } = useAuthBootstrap();
  if (!bootstrap?.selectedTenantId) return undefined;
  return bootstrap.memberships.find((m) => m.tenantId === bootstrap.selectedTenantId)?.tenantName;
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

/** PILOT-SETUP-001B4: tenant identity is never part of the payload -- the
 * backend derives it from the request's own tenant context (same mechanism
 * every other command here relies on), so this mutation carries only the
 * `FarmCreate` fields the operator actually filled in. */
export function useCreateFarm() {
  const tenantId = useSelectedTenantId();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: FarmCreate) => api.createFarm(payload),
    onSuccess: () => {
      if (!tenantId) return;
      queryClient.invalidateQueries({ queryKey: queryKeys.farms(tenantId) });
    },
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

/** PILOT-SETUP-001B5: generic Location setup -- single create and
 * range/generator bulk-children, against the existing generic Location
 * domain. Both invalidate the same `locationsTree` key the read side
 * already uses, mirroring `useCreateGreenhouseSetup`'s own invalidation. */
export function useCreateLocation(farmId: string) {
  const tenantId = useSelectedTenantId();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: LocationCreate) => api.createLocation(farmId, payload),
    onSuccess: () => {
      if (!tenantId) return;
      queryClient.invalidateQueries({ queryKey: queryKeys.locationsTree(tenantId, farmId) });
    },
  });
}

export function useBulkCreateLocationChildren(farmId: string) {
  const tenantId = useSelectedTenantId();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ parentId, payload }: { parentId: string; payload: LocationBulkChildrenCreate }) =>
      api.bulkCreateLocationChildren(farmId, parentId, payload),
    onSuccess: () => {
      if (!tenantId) return;
      queryClient.invalidateQueries({ queryKey: queryKeys.locationsTree(tenantId, farmId) });
    },
  });
}

// UX-IA-001 -- Location maintenance lifecycle: name update, deactivate,
// reactivate. All three invalidate the same `locationsTree` key the read
// side and the two create mutations above already use.

export function useUpdateLocation(farmId: string) {
  const tenantId = useSelectedTenantId();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ locationId, payload }: { locationId: string; payload: LocationUpdate }) =>
      api.updateLocation(farmId, locationId, payload),
    onSuccess: () => {
      if (!tenantId) return;
      queryClient.invalidateQueries({ queryKey: queryKeys.locationsTree(tenantId, farmId) });
    },
  });
}

export function useDeactivateLocation(farmId: string) {
  const tenantId = useSelectedTenantId();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ locationId, payload }: { locationId: string; payload: LocationDeactivate }) =>
      api.deactivateLocation(farmId, locationId, payload),
    onSuccess: () => {
      if (!tenantId) return;
      queryClient.invalidateQueries({ queryKey: queryKeys.locationsTree(tenantId, farmId) });
    },
  });
}

export function useReactivateLocation(farmId: string) {
  const tenantId = useSelectedTenantId();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ locationId, payload }: { locationId: string; payload: LocationReactivate }) =>
      api.reactivateLocation(farmId, locationId, payload),
    onSuccess: () => {
      if (!tenantId) return;
      queryClient.invalidateQueries({ queryKey: queryKeys.locationsTree(tenantId, farmId) });
    },
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

// --- PILOT-SETUP-001B8 -----------------------------------------------------
// Persisted-state Setup Checklist / Readiness -- a short staleTime (rather
// than the reference-data tier above) so returning to the page after making
// a setup change elsewhere reflects it without requiring a manual refresh,
// while a manual refetch() (exposed by useQuery itself) covers the rest.
export function useFarmSetupReadiness(farmId: string) {
  const tenantId = useSelectedTenantId();
  return useQuery({
    queryKey: queryKeys.farmSetupReadiness(tenantId ?? "", farmId),
    queryFn: ({ signal }) => api.getFarmSetupReadiness(farmId, signal),
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

export function useCreateCrop() {
  const tenantId = useSelectedTenantId();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: CropCreate) => api.createCrop(payload),
    onSuccess: () => {
      if (!tenantId) return;
      queryClient.invalidateQueries({ queryKey: queryKeys.crops(tenantId) });
    },
  });
}

export function useCreateVariety(cropId: string) {
  const tenantId = useSelectedTenantId();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: VarietyCreate) => api.createVariety(cropId, payload),
    onSuccess: () => {
      if (!tenantId) return;
      queryClient.invalidateQueries({ queryKey: queryKeys.varieties(tenantId, cropId) });
    },
  });
}

// --- PILOT-SETUP-001B6 -------------------------------------------------------
// Production System master data -- tenant-scoped, mirrors the Crop pattern
// immediately above (list + create only, no update/deactivate endpoint
// exists on the backend for this resource).

export function useProductionSystems() {
  const tenantId = useSelectedTenantId();
  return useQuery({
    queryKey: queryKeys.productionSystems(tenantId ?? ""),
    queryFn: ({ signal }) => api.listProductionSystems(signal),
    staleTime: STALE_REFERENCE_MS,
    enabled: Boolean(tenantId),
  });
}

export function useCreateProductionSystem() {
  const tenantId = useSelectedTenantId();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: ProductionSystemCreate) => api.createProductionSystem(payload),
    onSuccess: () => {
      if (!tenantId) return;
      queryClient.invalidateQueries({ queryKey: queryKeys.productionSystems(tenantId) });
    },
  });
}

// --- PILOT-SETUP-001B6 / B6A --------------------------------------------------
// Workflow master configuration: Workflow (crop/variety/production-system
// shell) -> draft WorkflowVersion -> Stages/Transitions -> explicit Publish.
// B6A closed the resumability gap B6 identified: `GET /workflows/{id}` and
// `GET /workflows/{id}/versions` now exist (mirroring the GradeDefinition/
// PackSpecification version-catalog pattern), so a Workflow's own shell
// fields and its full draft/published/retired version catalog are each
// directly fetchable -- an unfinished draft is rediscoverable after
// navigating away, not just within the tab that created it.

export function useWorkflows() {
  const tenantId = useSelectedTenantId();
  return useQuery({
    queryKey: queryKeys.workflows(tenantId ?? ""),
    queryFn: ({ signal }) => api.listWorkflows(signal),
    staleTime: STALE_LIST_MS,
    enabled: Boolean(tenantId),
  });
}

export function useCreateWorkflow() {
  const tenantId = useSelectedTenantId();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: WorkflowCreate) => api.createWorkflow(payload),
    onSuccess: () => {
      if (!tenantId) return;
      queryClient.invalidateQueries({ queryKey: queryKeys.workflows(tenantId) });
    },
  });
}

export function useWorkflow(workflowId: string) {
  const tenantId = useSelectedTenantId();
  return useQuery({
    queryKey: queryKeys.workflow(tenantId ?? "", workflowId),
    queryFn: ({ signal }) => api.getWorkflow(workflowId, signal),
    staleTime: STALE_DETAIL_MS,
    enabled: Boolean(tenantId) && Boolean(workflowId),
  });
}

export function useWorkflowVersions(workflowId: string) {
  const tenantId = useSelectedTenantId();
  return useQuery({
    queryKey: queryKeys.workflowVersions(tenantId ?? "", workflowId),
    queryFn: ({ signal }) => api.listWorkflowVersions(workflowId, signal),
    staleTime: STALE_DETAIL_MS,
    enabled: Boolean(tenantId) && Boolean(workflowId),
  });
}

export function useCreateWorkflowDraftVersion() {
  const tenantId = useSelectedTenantId();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (workflowId: string) => api.createWorkflowDraftVersion(workflowId),
    onSuccess: (_version, workflowId) => {
      if (!tenantId) return;
      queryClient.invalidateQueries({ queryKey: queryKeys.workflowVersions(tenantId, workflowId) });
    },
  });
}

export function useWorkflowVersion(workflowId: string, versionId: string | null) {
  const tenantId = useSelectedTenantId();
  return useQuery({
    queryKey: queryKeys.workflowVersion(tenantId ?? "", workflowId, versionId ?? ""),
    queryFn: ({ signal }) => api.getWorkflowVersion(workflowId, versionId as string, signal),
    staleTime: STALE_DETAIL_MS,
    enabled: Boolean(tenantId) && Boolean(versionId),
  });
}

export function useAddWorkflowStage(workflowId: string, versionId: string) {
  const tenantId = useSelectedTenantId();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: WorkflowStageCreate) => api.addWorkflowStage(workflowId, versionId, payload),
    onSuccess: () => {
      if (!tenantId) return;
      queryClient.invalidateQueries({ queryKey: queryKeys.workflowVersion(tenantId, workflowId, versionId) });
    },
  });
}

export function useAddWorkflowTransition(workflowId: string, versionId: string) {
  const tenantId = useSelectedTenantId();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: WorkflowTransitionCreate) => api.addWorkflowTransition(workflowId, versionId, payload),
    onSuccess: () => {
      if (!tenantId) return;
      queryClient.invalidateQueries({ queryKey: queryKeys.workflowVersion(tenantId, workflowId, versionId) });
    },
  });
}

export function usePublishWorkflowVersion(workflowId: string, versionId: string) {
  const tenantId = useSelectedTenantId();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => api.publishWorkflowVersion(workflowId, versionId),
    onSuccess: () => {
      if (!tenantId) return;
      queryClient.invalidateQueries({ queryKey: queryKeys.workflowVersion(tenantId, workflowId, versionId) });
      queryClient.invalidateQueries({ queryKey: queryKeys.workflows(tenantId) });
      // Publishing this version may also retire a previously-published one
      // (see workflow_service.publish_version) -- the version catalog's
      // states must be refreshed, not just this one version's own detail.
      queryClient.invalidateQueries({ queryKey: queryKeys.workflowVersions(tenantId, workflowId) });
    },
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

export function useTrolleyLevels(farmId: string, trolleyId: string) {
  const tenantId = useSelectedTenantId();
  return useQuery({
    queryKey: queryKeys.trolleyLevels(tenantId ?? "", farmId, trolleyId),
    queryFn: ({ signal }) => api.listTrolleyLevels(farmId, trolleyId, signal),
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
 * Tray resting on that Trolley's resolved location) and asset-level Level
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
        queryKey: queryKeys.trolleyLevels(tenantId, farmId, variables.trolley_id),
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

// --- PILOT-SETUP-001B5 -------------------------------------------------------
// Physical Carrier registration -- farm-scoped (unlike CarrierSpecification
// above). Registration only: creates the reusable physical object, never an
// Occupancy/Movement/Crop Batch population.

export function useCarriers(farmId: string) {
  const tenantId = useSelectedTenantId();
  return useQuery({
    queryKey: queryKeys.carriers(tenantId ?? "", farmId),
    queryFn: ({ signal }) => api.listCarriers(farmId, undefined, signal),
    staleTime: STALE_LIST_MS,
    enabled: Boolean(tenantId),
  });
}

export function useRegisterCarrier(farmId: string) {
  const tenantId = useSelectedTenantId();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: CarrierCreate) => api.registerCarrier(farmId, payload),
    onSuccess: () => {
      if (!tenantId) return;
      queryClient.invalidateQueries({ queryKey: queryKeys.carriers(tenantId, farmId) });
    },
  });
}

export function useBulkRegisterCarriers(farmId: string) {
  const tenantId = useSelectedTenantId();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: CarrierBulkCreate) => api.bulkRegisterCarriers(farmId, payload),
    onSuccess: () => {
      if (!tenantId) return;
      queryClient.invalidateQueries({ queryKey: queryKeys.carriers(tenantId, farmId) });
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

// --- VINES-OPS-001A ----------------------------------------------------------
// InterVines Transplant operator UI: Grow Cube pool eligibility read (source
// picking reuses `useSeedlingBiologicalTrays` above unchanged -- eligibility
// for a Seedling source is identical regardless of which downstream
// destination it feeds), the compact aggregated read view, its per-row
// drill-down, and the composite submit itself.

export function useAvailableGrowCubePools(farmId: string) {
  const tenantId = useSelectedTenantId();
  return useQuery({
    queryKey: queryKeys.availableGrowCubePools(tenantId ?? "", farmId),
    queryFn: ({ signal }) => api.listAvailableGrowCubePools(farmId, signal),
    staleTime: STALE_DETAIL_MS,
    enabled: Boolean(tenantId),
  });
}

export function useIntervinesPlacements(farmId: string) {
  const tenantId = useSelectedTenantId();
  return useQuery({
    queryKey: queryKeys.intervinesPlacements(tenantId ?? "", farmId),
    queryFn: ({ signal }) => api.listIntervinesPlacements(farmId, signal),
    staleTime: STALE_LIST_MS,
    enabled: Boolean(tenantId),
  });
}

/** On-demand only (mirrors `useLocationOccupants`'s own pattern): fetched
 * only once an operator actually expands one aggregated placement row's
 * drill-down, never for every row up front. */
export function useIntervinesPlacementGrowCubes(farmId: string, batchId: string | null, tableId: string | null) {
  const tenantId = useSelectedTenantId();
  return useQuery({
    queryKey: queryKeys.intervinesPlacementGrowCubes(tenantId ?? "", farmId, batchId ?? "", tableId ?? ""),
    queryFn: ({ signal }) => api.listIntervinesPlacementGrowCubes(farmId, batchId as string, tableId as string, signal),
    staleTime: STALE_DETAIL_MS,
    enabled: Boolean(tenantId) && Boolean(batchId) && Boolean(tableId),
  });
}

/** Idempotency key lives in the payload itself, same replay-safe pattern as
 * `useRecordIntersaladsTransplant`. Success changes source availability, the
 * Grow Cube pool, and the InterVines read view -- all three are invalidated. */
export function useRecordIntervinesTransplant(farmId: string) {
  const tenantId = useSelectedTenantId();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ batchId, payload }: { batchId: string; payload: IntervinesTransplantCreate }) =>
      api.recordIntervinesTransplant(farmId, batchId, payload),
    onSuccess: () => {
      if (!tenantId) return;
      queryClient.invalidateQueries({ queryKey: queryKeys.seedlingBiologicalTrays(tenantId, farmId) });
      queryClient.invalidateQueries({ queryKey: queryKeys.availableGrowCubePools(tenantId, farmId) });
      queryClient.invalidateQueries({ queryKey: queryKeys.intervinesPlacements(tenantId, farmId) });
    },
    // Section 10 (frozen, mirrors InterSalads): a 409 means the state this
    // draft was built against has changed elsewhere (the source or the Grow
    // Cube pool just changed) -- never auto-resubmit, only refresh the
    // authoritative queries the draft depends on.
    onError: (error) => {
      if (!tenantId || !(error instanceof AppError) || error.kind !== "conflict") return;
      queryClient.invalidateQueries({ queryKey: queryKeys.seedlingBiologicalTrays(tenantId, farmId) });
      queryClient.invalidateQueries({ queryKey: queryKeys.availableGrowCubePools(tenantId, farmId) });
    },
  });
}

// --- VINES-OPS-001B ----------------------------------------------------------
// Vines Production Transfer operator UI: source picking reuses
// `useIntervinesPlacements` above unchanged (each aggregated InterVines row
// IS a legitimate transfer source), Grow Bag pool eligibility read
// (optionally Gutter-scoped for the true placeable-capacity ceiling), the
// compact aggregated Vines Production read view, its per-row drill-down, and
// the composite submit itself.

export function useAvailableGrowBagPools(farmId: string, destinationGrowGutterId?: string) {
  const tenantId = useSelectedTenantId();
  return useQuery({
    queryKey: queryKeys.availableGrowBagPools(tenantId ?? "", farmId, destinationGrowGutterId ?? ""),
    queryFn: ({ signal }) => api.listAvailableGrowBagPools(farmId, destinationGrowGutterId, signal),
    staleTime: STALE_DETAIL_MS,
    enabled: Boolean(tenantId),
  });
}

export function useVinesProductionPlacements(farmId: string) {
  const tenantId = useSelectedTenantId();
  return useQuery({
    queryKey: queryKeys.vinesProductionPlacements(tenantId ?? "", farmId),
    queryFn: ({ signal }) => api.listVinesProductionPlacements(farmId, signal),
    staleTime: STALE_LIST_MS,
    enabled: Boolean(tenantId),
  });
}

/** On-demand only (mirrors `useIntervinesPlacementGrowCubes`'s own pattern):
 * fetched only once an operator expands one aggregated placement row's
 * drill-down. */
export function useVinesProductionPlacementGrowBags(farmId: string, batchId: string | null, gutterId: string | null) {
  const tenantId = useSelectedTenantId();
  return useQuery({
    queryKey: queryKeys.vinesProductionPlacementGrowBags(tenantId ?? "", farmId, batchId ?? "", gutterId ?? ""),
    queryFn: ({ signal }) => api.listVinesProductionPlacementGrowBags(farmId, batchId as string, gutterId as string, signal),
    staleTime: STALE_DETAIL_MS,
    enabled: Boolean(tenantId) && Boolean(batchId) && Boolean(gutterId),
  });
}

/** Idempotency key lives in the payload itself, same replay-safe pattern as
 * `useRecordIntervinesTransplant`. Success changes InterVines availability
 * (the source Grow Cubes are consumed), the Grow Bag pool, and the Vines
 * Production read view -- all three are invalidated. */
export function useRecordVinesProductionTransfer(farmId: string) {
  const tenantId = useSelectedTenantId();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ batchId, payload }: { batchId: string; payload: VinesProductionTransferCreate }) =>
      api.recordVinesProductionTransfer(farmId, batchId, payload),
    onSuccess: () => {
      if (!tenantId) return;
      queryClient.invalidateQueries({ queryKey: queryKeys.intervinesPlacements(tenantId, farmId) });
      queryClient.invalidateQueries({ queryKey: queryKeys.availableGrowBagPools(tenantId, farmId, "") });
      queryClient.invalidateQueries({ queryKey: queryKeys.vinesProductionPlacements(tenantId, farmId) });
    },
    // Section 10 (frozen, mirrors InterVines/InterSalads): a 409 means the
    // state this draft was built against has changed elsewhere -- never
    // auto-resubmit, only refresh the authoritative queries the draft
    // depends on.
    onError: (error) => {
      if (!tenantId || !(error instanceof AppError) || error.kind !== "conflict") return;
      queryClient.invalidateQueries({ queryKey: queryKeys.intervinesPlacements(tenantId, farmId) });
      queryClient.invalidateQueries({ queryKey: queryKeys.availableGrowBagPools(tenantId, farmId, "") });
    },
  });
}

// --- VINES-OPS-002 ------------------------------------------------------------
// Vines Production plant loss (Biological Disposition): current population +
// drill-down live in the same `vinesProductionPlacements`/`vinesProduction
// PlacementGrowBags` queries already established by 001B (now enriched with
// living/lost data) -- a successful record/correct invalidates BOTH those and
// its own history query, mirroring `useRecordProductionDisposition`'s own
// established discipline for the sibling Leafy authority.

export function useVinesProductionDispositionHistory(farmId: string, batchId?: string) {
  const tenantId = useSelectedTenantId();
  return useQuery({
    queryKey: queryKeys.vinesProductionDispositionHistory(tenantId ?? "", farmId, batchId ?? ""),
    queryFn: ({ signal }) => api.listVinesProductionDispositionHistory(farmId, { batchId }, signal),
    staleTime: STALE_DETAIL_MS,
    enabled: Boolean(tenantId),
  });
}

function _invalidateVinesProductionDisposition(
  queryClient: ReturnType<typeof useQueryClient>, tenantId: string, farmId: string,
) {
  queryClient.invalidateQueries({ queryKey: queryKeys.vinesProductionPlacements(tenantId, farmId) });
  queryClient.invalidateQueries({
    queryKey: ["tenant", tenantId, "farms", farmId, "vines-production", "placements"],
  });
  queryClient.invalidateQueries({
    queryKey: ["tenant", tenantId, "farms", farmId, "vines-production", "dispositions"],
  });
}

export function useRecordVinesGrowCubeDisposition(farmId: string) {
  const tenantId = useSelectedTenantId();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: RecordVinesGrowCubeDispositionCreate) => api.recordVinesGrowCubeDisposition(farmId, payload),
    onSuccess: () => {
      if (!tenantId) return;
      _invalidateVinesProductionDisposition(queryClient, tenantId, farmId);
    },
    onError: (error) => {
      if (!tenantId || !(error instanceof AppError) || error.kind !== "conflict") return;
      _invalidateVinesProductionDisposition(queryClient, tenantId, farmId);
    },
  });
}

export function useCorrectVinesGrowCubeDisposition(farmId: string) {
  const tenantId = useSelectedTenantId();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ eventId, payload }: { eventId: string; payload: CorrectVinesGrowCubeDispositionCreate }) =>
      api.correctVinesGrowCubeDisposition(farmId, eventId, payload),
    onSuccess: () => {
      if (!tenantId) return;
      _invalidateVinesProductionDisposition(queryClient, tenantId, farmId);
    },
    onError: (error) => {
      if (!tenantId || !(error instanceof AppError) || error.kind !== "conflict") return;
      _invalidateVinesProductionDisposition(queryClient, tenantId, farmId);
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

// --- LEAFY-OPS-002 -----------------------------------------------------------
// Production relocation: the generic Location ancestor-path read (used to
// prefill "Move plate"'s destination Greenhouse/Zone/Span from the Plate's
// current Table) and the generic Movement command. A successful relocation
// invalidates Active Production Plates exactly like LEAFY-OPS-001's own
// disposition commands do, so the moved Plate's current placement refreshes
// automatically -- no separate "move" read of its own.

export function useLocationPath(farmId: string, locationId: string | null) {
  const tenantId = useSelectedTenantId();
  return useQuery({
    queryKey: queryKeys.locationPath(tenantId ?? "", farmId, locationId ?? "__none__"),
    queryFn: ({ signal }) => api.getLocationPath(farmId, locationId as string, signal),
    staleTime: STALE_DETAIL_MS,
    enabled: Boolean(tenantId) && Boolean(locationId),
  });
}

export function useRelocateLeafyProductionPlate(farmId: string) {
  const tenantId = useSelectedTenantId();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: MovementCreate) => api.createMovement(farmId, payload),
    onSuccess: () => {
      if (!tenantId) return;
      queryClient.invalidateQueries({ queryKey: queryKeys.activeProductionPlates(tenantId, farmId, "") });
    },
    onError: (error) => {
      if (!tenantId || !(error instanceof AppError) || error.kind !== "conflict") return;
      queryClient.invalidateQueries({ queryKey: queryKeys.activeProductionPlates(tenantId, farmId, "") });
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

// --- VINES-OPS-003 ------------------------------------------------------------
// Vines Harvestable sources / Harvest history reads, and the record command
// -- mirrors HARVEST-OPS-001 SLICE 2's own invalidation discipline exactly.

export function useVinesHarvestableSources(farmId: string, batchId?: string) {
  const tenantId = useSelectedTenantId();
  return useQuery({
    queryKey: queryKeys.vinesHarvestableSources(tenantId ?? "", farmId, batchId ?? ""),
    queryFn: ({ signal }) => api.listVinesHarvestableSources(farmId, batchId, signal),
    staleTime: STALE_DETAIL_MS,
    enabled: Boolean(tenantId),
  });
}

export function useVinesHarvests(farmId: string, batchId?: string) {
  const tenantId = useSelectedTenantId();
  return useQuery({
    queryKey: queryKeys.vinesHarvests(tenantId ?? "", farmId, batchId ?? ""),
    queryFn: ({ signal }) => api.listVinesHarvests(farmId, batchId, signal),
    staleTime: STALE_DETAIL_MS,
    enabled: Boolean(tenantId),
  });
}

export function useVinesHarvest(farmId: string, harvestEventId: string | null) {
  const tenantId = useSelectedTenantId();
  return useQuery({
    queryKey: queryKeys.vinesHarvest(tenantId ?? "", farmId, harvestEventId ?? ""),
    queryFn: ({ signal }) => api.getVinesHarvest(farmId, harvestEventId as string, signal),
    staleTime: STALE_DETAIL_MS,
    enabled: Boolean(tenantId) && Boolean(harvestEventId),
  });
}

function _invalidateVinesHarvest(queryClient: ReturnType<typeof useQueryClient>, tenantId: string, farmId: string) {
  queryClient.invalidateQueries({ queryKey: queryKeys.vinesHarvestableSources(tenantId, farmId, "") });
  queryClient.invalidateQueries({ queryKey: queryKeys.vinesHarvests(tenantId, farmId, "") });
  queryClient.invalidateQueries({
    queryKey: ["tenant", tenantId, "farms", farmId, "vines-production", "harvests", "detail"],
  });
}

export function useRecordVinesHarvest(farmId: string) {
  const tenantId = useSelectedTenantId();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: RecordVinesHarvestCreate) => api.recordVinesHarvest(farmId, payload),
    onSuccess: () => {
      if (!tenantId) return;
      _invalidateVinesHarvest(queryClient, tenantId, farmId);
    },
    onError: (error) => {
      if (!tenantId || !(error instanceof AppError) || error.kind !== "conflict") return;
      _invalidateVinesHarvest(queryClient, tenantId, farmId);
    },
  });
}

export function useCorrectVinesHarvestSourceLine(farmId: string) {
  const tenantId = useSelectedTenantId();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (
      { harvestEventId, harvestSourceLineId, payload }: {
        harvestEventId: string; harvestSourceLineId: string; payload: CorrectVinesHarvestSourceLineCreate;
      },
    ) => api.correctVinesHarvestSourceLine(farmId, harvestEventId, harvestSourceLineId, payload),
    onSuccess: () => {
      if (!tenantId) return;
      _invalidateVinesHarvest(queryClient, tenantId, farmId);
    },
    onError: (error) => {
      if (!tenantId || !(error instanceof AppError) || error.kind !== "conflict") return;
      _invalidateVinesHarvest(queryClient, tenantId, farmId);
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

/** PILOT-SETUP-001B7: every non-draft Grade Definition Version across the
 * tenant, labeled for the Pack Specification Version form's optional grade
 * picker. A DRAFT version can never be referenced by a Pack Specification
 * Version (`pack_specification_versions_enforce_insert_integrity` requires
 * non-DRAFT), so this excludes drafts up front rather than letting the
 * backend reject the choice after submission. Shares the same per-definition
 * version queries `useGradeVersionLabelMap` subscribes to (same query keys),
 * so this never doubles the network requests -- only the derived shape
 * differs (a filtered list here, a flat label map there). */
export function useSelectableGradeDefinitionVersions(): {
  versions: { id: string; label: string; status: string }[];
  isLoading: boolean;
} {
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
  const versions: { id: string; label: string; status: string }[] = [];
  definitions.forEach((d, i) => {
    for (const v of versionQueries[i]?.data ?? []) {
      if (v.status === "draft") continue;
      versions.push({ id: v.id, label: `${d.name} v${v.version_number} (${v.status})`, status: v.status });
    }
  });
  return { versions, isLoading: definitionsQuery.isLoading || versionQueries.some((q) => q.isLoading) };
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

// --- PILOT-SETUP-001B7 -------------------------------------------------------
// Grade Definitions / Packaging Units / Pack Specifications master-data
// setup UI: create/version/activate/retire commands, plus Packaging Unit
// reads (list-only, no versioning). Every read hook these commands depend on
// (useAllGradeDefinitions, useGradeDefinitionVersions, useAllPackSpecifications,
// usePackSpecificationVersions) already existed for the Grading/Packing
// operator pickers above -- reused unchanged here, so both surfaces share one
// cache. Invalidation is prefix-only (no trailing cropId/status segment) so
// every filtered cache slot for the affected resource is refreshed, not just
// the unfiltered "" one this page itself reads.

export function useCreateGradeDefinition() {
  const tenantId = useSelectedTenantId();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: GradeDefinitionCreate) => api.createGradeDefinition(payload),
    onSuccess: () => {
      if (!tenantId) return;
      queryClient.invalidateQueries({ queryKey: ["tenant", tenantId, "grade-definitions"] });
    },
  });
}

export function useCreateGradeDefinitionVersion(gradeDefinitionId: string) {
  const tenantId = useSelectedTenantId();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: GradeDefinitionVersionCreate) =>
      api.createGradeDefinitionVersion(gradeDefinitionId, payload),
    onSuccess: () => {
      if (!tenantId) return;
      queryClient.invalidateQueries({
        queryKey: ["tenant", tenantId, "grade-definitions", gradeDefinitionId, "versions"],
      });
    },
  });
}

/** Activation may also retire a previously-active version (supersession) --
 * the version catalog's full state is refreshed, not just this one version. */
export function useActivateGradeDefinitionVersion(gradeDefinitionId: string) {
  const tenantId = useSelectedTenantId();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ versionId, payload }: { versionId: string; payload: GradeDefinitionVersionActivate }) =>
      api.activateGradeDefinitionVersion(gradeDefinitionId, versionId, payload),
    onSuccess: () => {
      if (!tenantId) return;
      queryClient.invalidateQueries({
        queryKey: ["tenant", tenantId, "grade-definitions", gradeDefinitionId, "versions"],
      });
    },
  });
}

export function useRetireGradeDefinitionVersion(gradeDefinitionId: string) {
  const tenantId = useSelectedTenantId();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ versionId, payload }: { versionId: string; payload: GradeDefinitionVersionRetire }) =>
      api.retireGradeDefinitionVersion(gradeDefinitionId, versionId, payload),
    onSuccess: () => {
      if (!tenantId) return;
      queryClient.invalidateQueries({
        queryKey: ["tenant", tenantId, "grade-definitions", gradeDefinitionId, "versions"],
      });
    },
  });
}

export function usePackagingUnits() {
  const tenantId = useSelectedTenantId();
  return useQuery({
    queryKey: queryKeys.packagingUnits(tenantId ?? ""),
    queryFn: ({ signal }) => api.listPackagingUnits(undefined, signal),
    staleTime: STALE_REFERENCE_MS,
    enabled: Boolean(tenantId),
  });
}

export function useCreatePackagingUnit() {
  const tenantId = useSelectedTenantId();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: PackagingUnitCreate) => api.createPackagingUnit(payload),
    onSuccess: () => {
      if (!tenantId) return;
      queryClient.invalidateQueries({ queryKey: queryKeys.packagingUnits(tenantId) });
    },
  });
}

export function useUoms() {
  const tenantId = useSelectedTenantId();
  return useQuery({
    queryKey: queryKeys.uoms(tenantId ?? ""),
    queryFn: ({ signal }) => api.listUoms(signal),
    staleTime: STALE_REFERENCE_MS,
    enabled: Boolean(tenantId),
  });
}

export function useInventoryCategories(status?: string) {
  const tenantId = useSelectedTenantId();
  return useQuery({
    queryKey: [...queryKeys.inventoryCategories(tenantId ?? ""), status ?? "all"],
    queryFn: ({ signal }) => api.listInventoryCategories(status, signal),
    staleTime: STALE_REFERENCE_MS,
    enabled: Boolean(tenantId),
  });
}

export function useCreateInventoryCategory() {
  const tenantId = useSelectedTenantId();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: InventoryCategoryCreate) => api.createInventoryCategory(payload),
    onSuccess: () => {
      if (!tenantId) return;
      queryClient.invalidateQueries({ queryKey: queryKeys.inventoryCategories(tenantId) });
    },
  });
}

export function useUpdateInventoryCategory() {
  const tenantId = useSelectedTenantId();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ categoryId, payload }: { categoryId: string; payload: InventoryCategoryUpdate }) =>
      api.updateInventoryCategory(categoryId, payload),
    onSuccess: () => {
      if (!tenantId) return;
      queryClient.invalidateQueries({ queryKey: queryKeys.inventoryCategories(tenantId) });
    },
  });
}

export function useDeactivateInventoryCategory() {
  const tenantId = useSelectedTenantId();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ categoryId, payload }: { categoryId: string; payload: InventoryCategoryDeactivate }) =>
      api.deactivateInventoryCategory(categoryId, payload),
    onSuccess: () => {
      if (!tenantId) return;
      queryClient.invalidateQueries({ queryKey: queryKeys.inventoryCategories(tenantId) });
    },
  });
}

export function useReactivateInventoryCategory() {
  const tenantId = useSelectedTenantId();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ categoryId, payload }: { categoryId: string; payload: InventoryCategoryReactivate }) =>
      api.reactivateInventoryCategory(categoryId, payload),
    onSuccess: () => {
      if (!tenantId) return;
      queryClient.invalidateQueries({ queryKey: queryKeys.inventoryCategories(tenantId) });
    },
  });
}

export function useInventoryItems(params: { status?: string; categoryId?: string } = {}) {
  const tenantId = useSelectedTenantId();
  return useQuery({
    queryKey: [...queryKeys.inventoryItems(tenantId ?? ""), params.status ?? "all", params.categoryId ?? "all"],
    queryFn: ({ signal }) => api.listInventoryItems(params, signal),
    staleTime: STALE_REFERENCE_MS,
    enabled: Boolean(tenantId),
  });
}

export function useCreateInventoryItem() {
  const tenantId = useSelectedTenantId();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: InventoryItemCreate) => api.createInventoryItem(payload),
    onSuccess: () => {
      if (!tenantId) return;
      queryClient.invalidateQueries({ queryKey: queryKeys.inventoryItems(tenantId) });
    },
  });
}

export function useUpdateInventoryItem() {
  const tenantId = useSelectedTenantId();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ itemId, payload }: { itemId: string; payload: InventoryItemUpdate }) =>
      api.updateInventoryItem(itemId, payload),
    onSuccess: () => {
      if (!tenantId) return;
      queryClient.invalidateQueries({ queryKey: queryKeys.inventoryItems(tenantId) });
    },
  });
}

export function useDeactivateInventoryItem() {
  const tenantId = useSelectedTenantId();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ itemId, payload }: { itemId: string; payload: InventoryItemDeactivate }) =>
      api.deactivateInventoryItem(itemId, payload),
    onSuccess: () => {
      if (!tenantId) return;
      queryClient.invalidateQueries({ queryKey: queryKeys.inventoryItems(tenantId) });
    },
  });
}

export function useReactivateInventoryItem() {
  const tenantId = useSelectedTenantId();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ itemId, payload }: { itemId: string; payload: InventoryItemReactivate }) =>
      api.reactivateInventoryItem(itemId, payload),
    onSuccess: () => {
      if (!tenantId) return;
      queryClient.invalidateQueries({ queryKey: queryKeys.inventoryItems(tenantId) });
    },
  });
}

// --- STORE-INV-002A.1: Packaging Options -------------------------------------

export function useInventoryItemPackaging(params: { inventoryItemId?: string; status?: string } = {}) {
  const tenantId = useSelectedTenantId();
  return useQuery({
    queryKey: [...queryKeys.inventoryItemPackaging(tenantId ?? ""), params.inventoryItemId ?? "all", params.status ?? "all"],
    queryFn: ({ signal }) => api.listInventoryItemPackaging(params, signal),
    staleTime: STALE_REFERENCE_MS,
    enabled: Boolean(tenantId),
  });
}

export function useCreateInventoryItemPackaging() {
  const tenantId = useSelectedTenantId();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: InventoryItemPackagingCreate) => api.createInventoryItemPackaging(payload),
    onSuccess: () => {
      if (!tenantId) return;
      queryClient.invalidateQueries({ queryKey: queryKeys.inventoryItemPackaging(tenantId) });
    },
  });
}

export function useUpdateInventoryItemPackaging() {
  const tenantId = useSelectedTenantId();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ packagingId, payload }: { packagingId: string; payload: InventoryItemPackagingUpdate }) =>
      api.updateInventoryItemPackaging(packagingId, payload),
    onSuccess: () => {
      if (!tenantId) return;
      queryClient.invalidateQueries({ queryKey: queryKeys.inventoryItemPackaging(tenantId) });
    },
  });
}

export function useDeactivateInventoryItemPackaging() {
  const tenantId = useSelectedTenantId();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ packagingId, payload }: { packagingId: string; payload: InventoryItemPackagingDeactivate }) =>
      api.deactivateInventoryItemPackaging(packagingId, payload),
    onSuccess: () => {
      if (!tenantId) return;
      queryClient.invalidateQueries({ queryKey: queryKeys.inventoryItemPackaging(tenantId) });
    },
  });
}

export function useReactivateInventoryItemPackaging() {
  const tenantId = useSelectedTenantId();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ packagingId, payload }: { packagingId: string; payload: InventoryItemPackagingReactivate }) =>
      api.reactivateInventoryItemPackaging(packagingId, payload),
    onSuccess: () => {
      if (!tenantId) return;
      queryClient.invalidateQueries({ queryKey: queryKeys.inventoryItemPackaging(tenantId) });
    },
  });
}

// --- STORE-INV-002A.1: Seed Details -------------------------------------------
// No status field on this entity -- deliberately no deactivate/reactivate
// pair, only create/update/remove (docs/domain/STORE_INVENTORY_MODEL.md §F).

export function useSeedProfileForItem(itemId: string | undefined) {
  const tenantId = useSelectedTenantId();
  return useQuery({
    queryKey: queryKeys.seedProfileForItem(tenantId ?? "", itemId ?? ""),
    queryFn: ({ signal }) => api.getSeedProfileForItem(itemId as string, signal),
    staleTime: STALE_REFERENCE_MS,
    enabled: Boolean(tenantId) && Boolean(itemId),
  });
}

export function useCreateSeedProfile() {
  const tenantId = useSelectedTenantId();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: InventoryItemSeedProfileCreate) => api.createSeedProfile(payload),
    onSuccess: (_data, variables) => {
      if (!tenantId) return;
      queryClient.invalidateQueries({
        queryKey: queryKeys.seedProfileForItem(tenantId, variables.inventory_item_id),
      });
    },
  });
}

export function useUpdateSeedProfile() {
  const tenantId = useSelectedTenantId();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (
      { profileId, payload }: { profileId: string; itemId: string; payload: InventoryItemSeedProfileUpdate },
    ) => api.updateSeedProfile(profileId, payload),
    onSuccess: (_data, variables) => {
      if (!tenantId) return;
      queryClient.invalidateQueries({ queryKey: queryKeys.seedProfileForItem(tenantId, variables.itemId) });
    },
  });
}

export function useRemoveSeedProfile() {
  const tenantId = useSelectedTenantId();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (
      { profileId, payload }: { profileId: string; itemId: string; payload: InventoryItemSeedProfileRemove },
    ) => api.removeSeedProfile(profileId, payload),
    onSuccess: (_data, variables) => {
      if (!tenantId) return;
      queryClient.invalidateQueries({ queryKey: queryKeys.seedProfileForItem(tenantId, variables.itemId) });
    },
  });
}

// --- STORE-INV-002A.1: Goods Receipt -----------------------------------------
// Farm-scoped -- receiving is physical, happens at one Farm.

export function useGoodsReceipts(farmId: string | undefined) {
  const tenantId = useSelectedTenantId();
  return useQuery({
    queryKey: queryKeys.goodsReceipts(tenantId ?? "", farmId ?? ""),
    queryFn: ({ signal }) => api.listGoodsReceipts(farmId as string, signal),
    enabled: Boolean(tenantId) && Boolean(farmId),
  });
}

export function useGoodsReceipt(farmId: string | undefined, receiptId: string | undefined) {
  const tenantId = useSelectedTenantId();
  return useQuery({
    queryKey: queryKeys.goodsReceipt(tenantId ?? "", farmId ?? "", receiptId ?? ""),
    queryFn: ({ signal }) => api.getGoodsReceipt(farmId as string, receiptId as string, signal),
    enabled: Boolean(tenantId) && Boolean(farmId) && Boolean(receiptId),
  });
}

export function useRecordGoodsReceipt(farmId: string) {
  const tenantId = useSelectedTenantId();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: GoodsReceiptCreate) => api.recordGoodsReceipt(farmId, payload),
    onSuccess: () => {
      if (!tenantId) return;
      queryClient.invalidateQueries({ queryKey: queryKeys.goodsReceipts(tenantId, farmId) });
      // Receiving may affect any item's company-wide existence/usable
      // totals -- invalidate the whole inventory-items read branch rather
      // than guessing which specific item ids were touched.
      queryClient.invalidateQueries({ queryKey: ["tenant", tenantId, "inventory-items"] });
      queryClient.invalidateQueries({ queryKey: queryKeys.qualityWorkQueue(tenantId) });
    },
    onError: (error) => {
      if (!tenantId || !(error instanceof AppError) || error.kind !== "conflict") return;
      queryClient.invalidateQueries({ queryKey: queryKeys.goodsReceipts(tenantId, farmId) });
    },
  });
}

// --- STORE-INV-002A.1/.2: existence, usable-existence, provenance -----------
// Tenant-wide, never Farm-scoped -- selecting a different Farm must not
// change these numbers (docs/domain/STORE_INVENTORY_MODEL.md §13).

export function useItemExistence(itemId: string | undefined) {
  const tenantId = useSelectedTenantId();
  return useQuery({
    queryKey: queryKeys.itemExistence(tenantId ?? "", itemId ?? ""),
    queryFn: ({ signal }) => api.getItemExistence(itemId as string, signal),
    enabled: Boolean(tenantId) && Boolean(itemId),
  });
}

export function useItemUsableExistence(itemId: string | undefined) {
  const tenantId = useSelectedTenantId();
  return useQuery({
    queryKey: queryKeys.itemUsableExistence(tenantId ?? "", itemId ?? ""),
    queryFn: ({ signal }) => api.getItemUsableExistence(itemId as string, signal),
    enabled: Boolean(tenantId) && Boolean(itemId),
  });
}

export function useItemExistenceProvenance(itemId: string | undefined) {
  const tenantId = useSelectedTenantId();
  return useQuery({
    queryKey: queryKeys.itemExistenceProvenance(tenantId ?? "", itemId ?? ""),
    queryFn: ({ signal }) => api.getItemExistenceProvenance(itemId as string, signal),
    enabled: Boolean(tenantId) && Boolean(itemId),
  });
}

export function useCohortLedger(cohortId: string | undefined) {
  const tenantId = useSelectedTenantId();
  return useQuery({
    queryKey: queryKeys.cohortLedger(tenantId ?? "", cohortId ?? ""),
    queryFn: ({ signal }) => api.getCohortLedger(cohortId as string, signal),
    enabled: Boolean(tenantId) && Boolean(cohortId),
  });
}

/** Batches per-item existence + usable-existence reads for the Inventory
 * page's item-by-item table -- mirrors `useGradeVersionLabelMap`'s own
 * `useQueries` batching pattern exactly, never one hook call per item in a
 * loop (which would violate the Rules of Hooks). */
export function useItemsExistenceSummary(itemIds: string[]): {
  byItemId: Record<string, { existing: string | null; usable: string | null }>;
  isLoading: boolean;
} {
  const tenantId = useSelectedTenantId();
  const existenceQueries = useQueries({
    queries: itemIds.map((id) => ({
      queryKey: queryKeys.itemExistence(tenantId ?? "", id),
      queryFn: ({ signal }: { signal: AbortSignal }) => api.getItemExistence(id, signal),
      enabled: Boolean(tenantId),
    })),
  });
  const usableQueries = useQueries({
    queries: itemIds.map((id) => ({
      queryKey: queryKeys.itemUsableExistence(tenantId ?? "", id),
      queryFn: ({ signal }: { signal: AbortSignal }) => api.getItemUsableExistence(id, signal),
      enabled: Boolean(tenantId),
    })),
  });
  const byItemId: Record<string, { existing: string | null; usable: string | null }> = {};
  itemIds.forEach((id, i) => {
    byItemId[id] = {
      existing: existenceQueries[i]?.data?.existing_quantity ?? null,
      usable: usableQueries[i]?.data?.usable_quantity ?? null,
    };
  });
  return {
    byItemId,
    isLoading: existenceQueries.some((q) => q.isLoading) || usableQueries.some((q) => q.isLoading),
  };
}

// --- STORE-INV-002A.2: Quality work queue and disposition commands ----------

export function useQualityWorkQueue() {
  const tenantId = useSelectedTenantId();
  return useQuery({
    queryKey: queryKeys.qualityWorkQueue(tenantId ?? ""),
    queryFn: ({ signal }) => api.getQualityWorkQueue(signal),
    enabled: Boolean(tenantId),
  });
}

function _invalidateQuality(
  queryClient: ReturnType<typeof useQueryClient>, tenantId: string,
  scope?: { farmId?: string; itemId?: string },
) {
  queryClient.invalidateQueries({ queryKey: queryKeys.qualityWorkQueue(tenantId) });
  queryClient.invalidateQueries({ queryKey: ["tenant", tenantId, "inventory-items"] });
  // STORE-INV-002B: a partial Quality action bucketed against a Bin also
  // reassigns physical custody (docs §11's integration seam) -- keep the
  // custody read model in sync too.
  queryClient.invalidateQueries({ queryKey: queryKeys.notPutAwayQueue(tenantId) });
  queryClient.invalidateQueries({ queryKey: ["tenant", tenantId, "inventory-quantity-cohorts"] });
  // PILOT-BLOCKER-005: a disposition change affects which lots/cohorts are
  // usable, which in turn feeds Farm-scoped availability and FEFO issuable-
  // source selection (docs/domain/STORE_INVENTORY_MODEL.md §9) -- these
  // live under a different key prefix ("farms", not "inventory-items") so
  // the broad invalidations above never reach them on their own.
  if (scope?.farmId && scope?.itemId) {
    queryClient.invalidateQueries({ queryKey: queryKeys.itemFarmAvailability(tenantId, scope.farmId, scope.itemId) });
    queryClient.invalidateQueries({ queryKey: queryKeys.issuableSources(tenantId, scope.farmId, scope.itemId) });
  }
}

export function useRecordQualityDisposition() {
  const tenantId = useSelectedTenantId();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ payload }: { payload: QualityDispositionCreate; farmId?: string; itemId?: string }) =>
      api.recordQualityDisposition(payload),
    onSuccess: (_data, variables) => {
      if (!tenantId) return;
      _invalidateQuality(queryClient, tenantId, variables);
    },
    onError: (error, variables) => {
      if (!tenantId || !(error instanceof AppError) || error.kind !== "conflict") return;
      _invalidateQuality(queryClient, tenantId, variables);
    },
  });
}

export function useCorrectQualityDisposition() {
  const tenantId = useSelectedTenantId();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ payload }: { payload: QualityDispositionCorrectionCreate; farmId?: string; itemId?: string }) =>
      api.correctQualityDisposition(payload),
    onSuccess: (_data, variables) => {
      if (!tenantId) return;
      _invalidateQuality(queryClient, tenantId, variables);
    },
    onError: (error, variables) => {
      if (!tenantId || !(error instanceof AppError) || error.kind !== "conflict") return;
      _invalidateQuality(queryClient, tenantId, variables);
    },
  });
}

export function useApplyQualityDispositionToPartialQuantity() {
  const tenantId = useSelectedTenantId();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ payload }: { payload: QualityPartialDispositionCreate; farmId?: string; itemId?: string }) =>
      api.applyQualityDispositionToPartialQuantity(payload),
    onSuccess: (_data, variables) => {
      if (!tenantId) return;
      _invalidateQuality(queryClient, tenantId, variables);
    },
    onError: (error, variables) => {
      if (!tenantId || !(error instanceof AppError) || error.kind !== "conflict") return;
      _invalidateQuality(queryClient, tenantId, variables);
    },
  });
}

export function useCorrectQualityDispositionForPartialQuantity() {
  const tenantId = useSelectedTenantId();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ payload }: { payload: QualityPartialCorrectionCreate; farmId?: string; itemId?: string }) =>
      api.correctQualityDispositionForPartialQuantity(payload),
    onSuccess: (_data, variables) => {
      if (!tenantId) return;
      _invalidateQuality(queryClient, tenantId, variables);
    },
    onError: (error, variables) => {
      if (!tenantId || !(error instanceof AppError) || error.kind !== "conflict") return;
      _invalidateQuality(queryClient, tenantId, variables);
    },
  });
}

// --- STORE-INV-002B: physical custody / putaway -----------------------------

export function useNotPutAwayQueue() {
  const tenantId = useSelectedTenantId();
  return useQuery({
    queryKey: queryKeys.notPutAwayQueue(tenantId ?? ""),
    queryFn: ({ signal }) => api.getNotPutAwayQueue(signal),
    enabled: Boolean(tenantId),
  });
}

export function useCohortStorageBreakdown(cohortId: string | undefined) {
  const tenantId = useSelectedTenantId();
  return useQuery({
    queryKey: queryKeys.cohortStorageBreakdown(tenantId ?? "", cohortId ?? ""),
    queryFn: ({ signal }) => api.getCohortStorageBreakdown(cohortId as string, signal),
    enabled: Boolean(tenantId) && Boolean(cohortId),
  });
}

export function useItemStorageBreakdown(itemId: string | undefined) {
  const tenantId = useSelectedTenantId();
  return useQuery({
    queryKey: queryKeys.itemStorageBreakdown(tenantId ?? "", itemId ?? ""),
    queryFn: ({ signal }) => api.getItemStorageBreakdown(itemId as string, signal),
    enabled: Boolean(tenantId) && Boolean(itemId),
  });
}

function _invalidateCustody(queryClient: ReturnType<typeof useQueryClient>, tenantId: string) {
  queryClient.invalidateQueries({ queryKey: queryKeys.notPutAwayQueue(tenantId) });
  queryClient.invalidateQueries({ queryKey: ["tenant", tenantId, "inventory-quantity-cohorts"] });
  queryClient.invalidateQueries({ queryKey: ["tenant", tenantId, "inventory-items"] });
}

export function useRecordInventoryPutaway() {
  const tenantId = useSelectedTenantId();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ farmId, payload }: { farmId: string; payload: InventoryPutawayCreate }) =>
      api.recordInventoryPutaway(farmId, payload),
    onSuccess: () => {
      if (!tenantId) return;
      _invalidateCustody(queryClient, tenantId);
    },
    onError: (error) => {
      if (!tenantId || !(error instanceof AppError) || error.kind !== "conflict") return;
      _invalidateCustody(queryClient, tenantId);
    },
  });
}

export function useRecordInventoryStorageTransfer() {
  const tenantId = useSelectedTenantId();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ farmId, payload }: { farmId: string; payload: InventoryStorageTransferCreate }) =>
      api.recordInventoryStorageTransfer(farmId, payload),
    onSuccess: () => {
      if (!tenantId) return;
      _invalidateCustody(queryClient, tenantId);
    },
    onError: (error) => {
      if (!tenantId || !(error instanceof AppError) || error.kind !== "conflict") return;
      _invalidateCustody(queryClient, tenantId);
    },
  });
}

// --- STORE-INV-003: Reservation & Issue --------------------------------------

function _invalidateReservationsAndIssues(queryClient: ReturnType<typeof useQueryClient>, tenantId: string, farmId: string) {
  queryClient.invalidateQueries({ queryKey: queryKeys.inventoryReservations(tenantId, farmId) });
  queryClient.invalidateQueries({ queryKey: queryKeys.inventoryIssues(tenantId, farmId) });
  queryClient.invalidateQueries({ queryKey: ["tenant", tenantId, "farms", farmId, "inventory-items"] });
  // Issue also moves physical custody -- keep the custody read model
  // (Not put away / per-Bin balances) in sync too.
  _invalidateCustody(queryClient, tenantId);
}

export function useInventoryReservations(farmId: string | undefined) {
  const tenantId = useSelectedTenantId();
  return useQuery({
    queryKey: queryKeys.inventoryReservations(tenantId ?? "", farmId ?? ""),
    queryFn: ({ signal }) => api.listInventoryReservations(farmId as string, signal),
    enabled: Boolean(tenantId) && Boolean(farmId),
  });
}

export function useInventoryReservation(reservationId: string | undefined) {
  const tenantId = useSelectedTenantId();
  return useQuery({
    queryKey: queryKeys.inventoryReservation(tenantId ?? "", reservationId ?? ""),
    queryFn: ({ signal }) => api.getInventoryReservation(reservationId as string, signal),
    enabled: Boolean(tenantId) && Boolean(reservationId),
  });
}

export function useCreateInventoryReservation() {
  const tenantId = useSelectedTenantId();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ farmId, payload }: { farmId: string; payload: InventoryReservationCreate }) =>
      api.createInventoryReservation(farmId, payload),
    onSuccess: (_data, { farmId }) => {
      if (!tenantId) return;
      _invalidateReservationsAndIssues(queryClient, tenantId, farmId);
    },
    onError: (error, { farmId }) => {
      if (!tenantId || !(error instanceof AppError) || error.kind !== "conflict") return;
      _invalidateReservationsAndIssues(queryClient, tenantId, farmId);
    },
  });
}

export function useReleaseInventoryReservationLine() {
  const tenantId = useSelectedTenantId();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (
      { lineId, payload }: { lineId: string; payload: InventoryReservationReleaseCreate; farmId: string },
    ) => api.releaseInventoryReservationLine(lineId, payload),
    onSuccess: (_data, { farmId }) => {
      if (!tenantId) return;
      _invalidateReservationsAndIssues(queryClient, tenantId, farmId);
    },
    onError: (error, { farmId }) => {
      if (!tenantId || !(error instanceof AppError) || error.kind !== "conflict") return;
      _invalidateReservationsAndIssues(queryClient, tenantId, farmId);
    },
  });
}

export function useInventoryIssues(farmId: string | undefined) {
  const tenantId = useSelectedTenantId();
  return useQuery({
    queryKey: queryKeys.inventoryIssues(tenantId ?? "", farmId ?? ""),
    queryFn: ({ signal }) => api.listInventoryIssues(farmId as string, signal),
    enabled: Boolean(tenantId) && Boolean(farmId),
  });
}

export function useRecordInventoryIssue() {
  const tenantId = useSelectedTenantId();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ farmId, payload }: { farmId: string; payload: InventoryIssueCreate }) =>
      api.recordInventoryIssue(farmId, payload),
    onSuccess: (_data, { farmId }) => {
      if (!tenantId) return;
      _invalidateReservationsAndIssues(queryClient, tenantId, farmId);
    },
    onError: (error, { farmId }) => {
      if (!tenantId || !(error instanceof AppError) || error.kind !== "conflict") return;
      _invalidateReservationsAndIssues(queryClient, tenantId, farmId);
    },
  });
}

export function useItemFarmAvailability(farmId: string | undefined, itemId: string | undefined) {
  const tenantId = useSelectedTenantId();
  return useQuery({
    queryKey: queryKeys.itemFarmAvailability(tenantId ?? "", farmId ?? "", itemId ?? ""),
    queryFn: ({ signal }) => api.getItemFarmAvailability(farmId as string, itemId as string, signal),
    enabled: Boolean(tenantId) && Boolean(farmId) && Boolean(itemId),
  });
}

export function useIssuableSources(farmId: string | undefined, itemId: string | undefined) {
  const tenantId = useSelectedTenantId();
  return useQuery({
    queryKey: queryKeys.issuableSources(tenantId ?? "", farmId ?? "", itemId ?? ""),
    queryFn: ({ signal }) => api.listIssuableSources(farmId as string, itemId as string, signal),
    enabled: Boolean(tenantId) && Boolean(farmId) && Boolean(itemId),
  });
}

// --- STORE-INV-004: Consumption, Return & Scrap ------------------------------

function _invalidateMaterialEvents(
  queryClient: ReturnType<typeof useQueryClient>, tenantId: string, farmId: string, issueLineId?: string,
) {
  queryClient.invalidateQueries({ queryKey: queryKeys.outstandingIssuedMaterial(tenantId, farmId) });
  if (issueLineId) {
    queryClient.invalidateQueries({ queryKey: queryKeys.issueLineReconciliation(tenantId, issueLineId) });
  }
  _invalidateReservationsAndIssues(queryClient, tenantId, farmId);
}

export function useOutstandingIssuedMaterial(farmId: string | undefined) {
  const tenantId = useSelectedTenantId();
  return useQuery({
    queryKey: queryKeys.outstandingIssuedMaterial(tenantId ?? "", farmId ?? ""),
    queryFn: ({ signal }) => api.listOutstandingIssuedMaterial(farmId as string, signal),
    enabled: Boolean(tenantId) && Boolean(farmId),
  });
}

export function useIssueLineReconciliation(issueLineId: string | undefined) {
  const tenantId = useSelectedTenantId();
  return useQuery({
    queryKey: queryKeys.issueLineReconciliation(tenantId ?? "", issueLineId ?? ""),
    queryFn: ({ signal }) => api.getIssueLineReconciliation(issueLineId as string, signal),
    enabled: Boolean(tenantId) && Boolean(issueLineId),
  });
}

export function useRecordInventoryConsumption() {
  const tenantId = useSelectedTenantId();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ payload }: { farmId: string; payload: InventoryConsumptionCreate }) =>
      api.recordInventoryConsumption(payload),
    onSuccess: (_data, { farmId, payload }) => {
      if (!tenantId) return;
      _invalidateMaterialEvents(queryClient, tenantId, farmId, payload.issue_line_id);
    },
    onError: (error, { farmId, payload }) => {
      if (!tenantId || !(error instanceof AppError) || error.kind !== "conflict") return;
      _invalidateMaterialEvents(queryClient, tenantId, farmId, payload.issue_line_id);
    },
  });
}

export function useRecordInventoryReturn() {
  const tenantId = useSelectedTenantId();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ payload }: { farmId: string; payload: InventoryReturnCreate }) =>
      api.recordInventoryReturn(payload),
    onSuccess: (_data, { farmId, payload }) => {
      if (!tenantId) return;
      _invalidateMaterialEvents(queryClient, tenantId, farmId, payload.issue_line_id);
      _invalidateCustody(queryClient, tenantId);
    },
    onError: (error, { farmId, payload }) => {
      if (!tenantId || !(error instanceof AppError) || error.kind !== "conflict") return;
      _invalidateMaterialEvents(queryClient, tenantId, farmId, payload.issue_line_id);
      _invalidateCustody(queryClient, tenantId);
    },
  });
}

export function useRecordInventoryScrap() {
  const tenantId = useSelectedTenantId();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ payload }: { farmId: string; payload: InventoryScrapCreate }) => api.recordInventoryScrap(payload),
    onSuccess: (_data, { farmId, payload }) => {
      if (!tenantId) return;
      _invalidateMaterialEvents(queryClient, tenantId, farmId, payload.issue_line_id ?? undefined);
      _invalidateCustody(queryClient, tenantId);
    },
    onError: (error, { farmId, payload }) => {
      if (!tenantId || !(error instanceof AppError) || error.kind !== "conflict") return;
      _invalidateMaterialEvents(queryClient, tenantId, farmId, payload.issue_line_id ?? undefined);
      _invalidateCustody(queryClient, tenantId);
    },
  });
}

export function useRetirePackagingUnit() {
  const tenantId = useSelectedTenantId();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ packagingUnitId, payload }: { packagingUnitId: string; payload: PackagingUnitRetire }) =>
      api.retirePackagingUnit(packagingUnitId, payload),
    onSuccess: () => {
      if (!tenantId) return;
      queryClient.invalidateQueries({ queryKey: queryKeys.packagingUnits(tenantId) });
    },
  });
}

export function useCreatePackSpecification() {
  const tenantId = useSelectedTenantId();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: PackSpecificationCreate) => api.createPackSpecification(payload),
    onSuccess: () => {
      if (!tenantId) return;
      queryClient.invalidateQueries({ queryKey: ["tenant", tenantId, "pack-specifications"] });
    },
  });
}

export function useCreatePackSpecificationVersion(packSpecificationId: string) {
  const tenantId = useSelectedTenantId();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: PackSpecificationVersionCreate) =>
      api.createPackSpecificationVersion(packSpecificationId, payload),
    onSuccess: () => {
      if (!tenantId) return;
      queryClient.invalidateQueries({
        queryKey: ["tenant", tenantId, "pack-specifications", packSpecificationId, "versions"],
      });
    },
  });
}

/** Activation may also retire a previously-active version (supersession) --
 * the version catalog's full state is refreshed, not just this one version. */
export function useActivatePackSpecificationVersion(packSpecificationId: string) {
  const tenantId = useSelectedTenantId();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ versionId, payload }: { versionId: string; payload: PackSpecificationVersionActivate }) =>
      api.activatePackSpecificationVersion(packSpecificationId, versionId, payload),
    onSuccess: () => {
      if (!tenantId) return;
      queryClient.invalidateQueries({
        queryKey: ["tenant", tenantId, "pack-specifications", packSpecificationId, "versions"],
      });
    },
  });
}

export function useRetirePackSpecificationVersion(packSpecificationId: string) {
  const tenantId = useSelectedTenantId();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ versionId, payload }: { versionId: string; payload: PackSpecificationVersionRetire }) =>
      api.retirePackSpecificationVersion(packSpecificationId, versionId, payload),
    onSuccess: () => {
      if (!tenantId) return;
      queryClient.invalidateQueries({
        queryKey: ["tenant", tenantId, "pack-specifications", packSpecificationId, "versions"],
      });
    },
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

// --- UI-OPT-001: Traceability (read-only) --------------------------------
// Backed by backend endpoints that already existed before this ticket --
// see the comment on `getFinishedGoodsLotTrace`/`getCropBatchImpact`/
// `getHarvestedProduceLotImpact` in `lib/api/client.ts`.

export function useFinishedGoodsLotTrace(farmId: string, finishedGoodsLotId: string | null) {
  const tenantId = useSelectedTenantId();
  return useQuery({
    queryKey: queryKeys.finishedGoodsLotTrace(tenantId ?? "", farmId, finishedGoodsLotId ?? ""),
    queryFn: ({ signal }) => api.getFinishedGoodsLotTrace(farmId, finishedGoodsLotId as string, signal),
    staleTime: STALE_DETAIL_MS,
    enabled: Boolean(tenantId) && Boolean(finishedGoodsLotId),
  });
}

export function useCropBatchImpact(farmId: string, batchId: string | null) {
  const tenantId = useSelectedTenantId();
  return useQuery({
    queryKey: queryKeys.cropBatchImpact(tenantId ?? "", farmId, batchId ?? ""),
    queryFn: ({ signal }) => api.getCropBatchImpact(farmId, batchId as string, signal),
    staleTime: STALE_DETAIL_MS,
    enabled: Boolean(tenantId) && Boolean(batchId),
  });
}

export function useHarvestedProduceLotImpact(farmId: string, produceLotId: string | null) {
  const tenantId = useSelectedTenantId();
  return useQuery({
    queryKey: queryKeys.harvestedProduceLotImpact(tenantId ?? "", farmId, produceLotId ?? ""),
    queryFn: ({ signal }) => api.getHarvestedProduceLotImpact(farmId, produceLotId as string, signal),
    staleTime: STALE_DETAIL_MS,
    enabled: Boolean(tenantId) && Boolean(produceLotId),
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

// --- PILOT-SETUP-001B3 -------------------------------------------------------
// Platform Admin Tenant onboarding. Deliberately does NOT use
// useSelectedTenantId()/tenant-prefixed query keys -- these calls are
// platform-level and tenant-independent (see queryKeys.platformTenants(),
// app/api/[...path]/route.ts), unlike every tenant-scoped hook above.

export function usePlatformTenants() {
  return useQuery({
    queryKey: queryKeys.platformTenants(),
    queryFn: ({ signal }) => api.listPlatformTenants(signal),
    staleTime: STALE_LIST_MS,
  });
}

export function usePlatformTenant(tenantId: string) {
  return useQuery({
    queryKey: queryKeys.platformTenant(tenantId),
    queryFn: ({ signal }) => api.getPlatformTenant(tenantId, signal),
    staleTime: STALE_DETAIL_MS,
    enabled: Boolean(tenantId),
  });
}

export function useCreatePlatformTenant() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: PlatformTenantOnboardingCreate) => api.createPlatformTenant(payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.platformTenants() });
    },
  });
}

// --- AGRONOMY-OPS-001 --------------------------------------------------------
// Crop Observations operator UI. Definitions are tenant-level (not
// farm-scoped, mirrors `/observation-definitions`'s own route shape);
// history and target selection are per-batch, so this workspace works
// identically for Nursery/Leafy/Vines batches without any stage-specific
// branching.

export function useObservationDefinitions() {
  const tenantId = useSelectedTenantId();
  return useQuery({
    queryKey: queryKeys.observationDefinitions(tenantId ?? ""),
    queryFn: ({ signal }) => api.listObservationDefinitions(signal),
    staleTime: STALE_REFERENCE_MS,
    enabled: Boolean(tenantId),
  });
}

export function useObservationHistory(farmId: string, batchId: string | null) {
  const tenantId = useSelectedTenantId();
  return useQuery({
    queryKey: queryKeys.observationHistory(tenantId ?? "", farmId, batchId ?? ""),
    queryFn: ({ signal }) => api.listObservations(farmId, batchId as string, signal),
    staleTime: STALE_LIST_MS,
    enabled: Boolean(tenantId) && Boolean(batchId),
  });
}

export function useBatchObservationTargets(farmId: string, batchId: string | null) {
  const tenantId = useSelectedTenantId();
  return useQuery({
    queryKey: queryKeys.observationTargets(tenantId ?? "", farmId, batchId ?? ""),
    queryFn: ({ signal }) => api.listBatchObservationTargets(farmId, batchId as string, signal),
    staleTime: STALE_DETAIL_MS,
    enabled: Boolean(tenantId) && Boolean(batchId),
  });
}

/** Idempotency key (`client_command_id`) lives in the payload itself, same
 * replay-safe pattern as every other command here. Success only refreshes
 * this batch's own observation history -- recording an Observation never
 * changes placement/occupancy/population, so no other query is invalidated. */
export function useRecordObservation(farmId: string) {
  const tenantId = useSelectedTenantId();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ batchId, payload }: { batchId: string; payload: ObservationEventCreate }) =>
      api.recordObservation(farmId, batchId, payload),
    onSuccess: (_result, variables) => {
      if (!tenantId) return;
      queryClient.invalidateQueries({
        queryKey: queryKeys.observationHistory(tenantId, farmId, variables.batchId),
      });
    },
  });
}

// --- PLANNING-OPS-001 ---------------------------------------------------------------
// Production Requirements (crop demand) and the Seeding Program (planned
// sowings intended to cover that demand). A Requirement's own fulfillment
// summary is derived from its Seeding Program Lines, so any Line mutation
// also invalidates the parent Requirement's list/detail queries -- never
// left stale after "Planned coverage"/"Gap" would have changed.

export function useProductionRequirements(farmId: string) {
  const tenantId = useSelectedTenantId();
  return useQuery({
    queryKey: queryKeys.productionRequirements(tenantId ?? "", farmId),
    queryFn: ({ signal }) => api.listProductionRequirements(farmId, signal),
    staleTime: STALE_LIST_MS,
    enabled: Boolean(tenantId),
  });
}

export function useProductionRequirement(farmId: string, requirementId: string | undefined) {
  const tenantId = useSelectedTenantId();
  return useQuery({
    queryKey: queryKeys.productionRequirement(tenantId ?? "", farmId, requirementId ?? ""),
    queryFn: ({ signal }) => api.getProductionRequirement(farmId, requirementId as string, signal),
    staleTime: STALE_DETAIL_MS,
    enabled: Boolean(tenantId) && Boolean(requirementId),
  });
}

export function useCreateProductionRequirement(farmId: string) {
  const tenantId = useSelectedTenantId();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: ProductionRequirementCreate) => api.createProductionRequirement(farmId, payload),
    onSuccess: () => {
      if (!tenantId) return;
      queryClient.invalidateQueries({ queryKey: queryKeys.productionRequirements(tenantId, farmId) });
    },
  });
}

function invalidateRequirement(
  queryClient: ReturnType<typeof useQueryClient>,
  tenantId: string | undefined,
  farmId: string,
  requirementId: string,
) {
  if (!tenantId) return;
  queryClient.invalidateQueries({ queryKey: queryKeys.productionRequirements(tenantId, farmId) });
  queryClient.invalidateQueries({ queryKey: queryKeys.productionRequirement(tenantId, farmId, requirementId) });
}

export function useUpdateProductionRequirement(farmId: string, requirementId: string) {
  const tenantId = useSelectedTenantId();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: ProductionRequirementUpdate) =>
      api.updateProductionRequirement(farmId, requirementId, payload),
    onSuccess: () => invalidateRequirement(queryClient, tenantId, farmId, requirementId),
  });
}

export function useCloseProductionRequirement(farmId: string, requirementId: string) {
  const tenantId = useSelectedTenantId();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: ProductionRequirementStatusCommand) =>
      api.closeProductionRequirement(farmId, requirementId, payload),
    onSuccess: () => invalidateRequirement(queryClient, tenantId, farmId, requirementId),
  });
}

export function useCancelProductionRequirement(farmId: string, requirementId: string) {
  const tenantId = useSelectedTenantId();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: ProductionRequirementStatusCommand) =>
      api.cancelProductionRequirement(farmId, requirementId, payload),
    onSuccess: () => invalidateRequirement(queryClient, tenantId, farmId, requirementId),
  });
}

export function useSeedingProgramLines(farmId: string) {
  const tenantId = useSelectedTenantId();
  return useQuery({
    queryKey: queryKeys.seedingProgramLines(tenantId ?? "", farmId),
    queryFn: ({ signal }) => api.listSeedingProgramLines(farmId, signal),
    staleTime: STALE_LIST_MS,
    enabled: Boolean(tenantId),
  });
}

export function useSeedingProgramLinesForRequirement(farmId: string, requirementId: string | undefined) {
  const tenantId = useSelectedTenantId();
  return useQuery({
    queryKey: queryKeys.seedingProgramLinesForRequirement(tenantId ?? "", farmId, requirementId ?? ""),
    queryFn: ({ signal }) => api.listSeedingProgramLinesForRequirement(farmId, requirementId as string, signal),
    staleTime: STALE_LIST_MS,
    enabled: Boolean(tenantId) && Boolean(requirementId),
  });
}

export function useSeedingProgramLine(farmId: string, lineId: string | undefined) {
  const tenantId = useSelectedTenantId();
  return useQuery({
    queryKey: queryKeys.seedingProgramLine(tenantId ?? "", farmId, lineId ?? ""),
    queryFn: ({ signal }) => api.getSeedingProgramLine(farmId, lineId as string, signal),
    staleTime: STALE_DETAIL_MS,
    enabled: Boolean(tenantId) && Boolean(lineId),
  });
}

function invalidateSeedingProgramLine(
  queryClient: ReturnType<typeof useQueryClient>,
  tenantId: string | undefined,
  farmId: string,
  requirementId: string,
  lineId?: string,
) {
  if (!tenantId) return;
  queryClient.invalidateQueries({ queryKey: queryKeys.seedingProgramLines(tenantId, farmId) });
  queryClient.invalidateQueries({
    queryKey: queryKeys.seedingProgramLinesForRequirement(tenantId, farmId, requirementId),
  });
  if (lineId) {
    queryClient.invalidateQueries({ queryKey: queryKeys.seedingProgramLine(tenantId, farmId, lineId) });
  }
  // A Line mutation always changes its parent Requirement's fulfillment
  // summary (planned coverage / gap / overplanned), so the Requirement
  // itself must be refreshed too.
  queryClient.invalidateQueries({ queryKey: queryKeys.productionRequirements(tenantId, farmId) });
  queryClient.invalidateQueries({ queryKey: queryKeys.productionRequirement(tenantId, farmId, requirementId) });
}

export function useCreateSeedingProgramLine(farmId: string, requirementId: string) {
  const tenantId = useSelectedTenantId();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: SeedingProgramLineCreate) =>
      api.createSeedingProgramLine(farmId, requirementId, payload),
    onSuccess: () => invalidateSeedingProgramLine(queryClient, tenantId, farmId, requirementId),
  });
}

export function useUpdateSeedingProgramLine(farmId: string, requirementId: string, lineId: string) {
  const tenantId = useSelectedTenantId();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: SeedingProgramLineUpdate) => api.updateSeedingProgramLine(farmId, lineId, payload),
    onSuccess: () => invalidateSeedingProgramLine(queryClient, tenantId, farmId, requirementId, lineId),
  });
}

export function useCancelSeedingProgramLine(farmId: string, requirementId: string, lineId: string) {
  const tenantId = useSelectedTenantId();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: SeedingProgramLineStatusCommand) => api.cancelSeedingProgramLine(farmId, lineId, payload),
    onSuccess: () => invalidateSeedingProgramLine(queryClient, tenantId, farmId, requirementId, lineId),
  });
}

// --- AUTHZ-OPS-001: Users & Roles administration -----------------------------
// Tenant-wide (no farmId) -- membership administration is not farm-scoped
// (CLAUDE.md/ticket section 14: current roles are tenant-wide, and this
// ticket does not invent farm-scoped access).

export function useMemberships() {
  const tenantId = useSelectedTenantId();
  return useQuery({
    queryKey: queryKeys.memberships(tenantId ?? ""),
    queryFn: ({ signal }) => api.listMemberships(signal),
    staleTime: STALE_LIST_MS,
    enabled: Boolean(tenantId),
  });
}

export function useAssignableRoles() {
  const tenantId = useSelectedTenantId();
  return useQuery({
    queryKey: queryKeys.assignableRoles(tenantId ?? ""),
    queryFn: ({ signal }) => api.listAssignableRoles(signal),
    staleTime: STALE_REFERENCE_MS,
    enabled: Boolean(tenantId),
  });
}

/** One-shot lookup triggered by an explicit "Add User" form action (not a
 * background query) -- the admin types an email and asks CMP to check it,
 * rather than every keystroke firing a request. */
export function useLookupUserByEmail() {
  return useMutation({
    mutationFn: (email: string) => api.lookupUserByEmail(email),
  });
}

function invalidateMemberships(queryClient: ReturnType<typeof useQueryClient>, tenantId: string | undefined) {
  if (!tenantId) return;
  queryClient.invalidateQueries({ queryKey: queryKeys.memberships(tenantId) });
}

export function useCreateMembership() {
  const tenantId = useSelectedTenantId();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: MembershipCreate) => api.createMembership(payload),
    onSuccess: () => invalidateMemberships(queryClient, tenantId),
  });
}

export function useChangeMembershipRole() {
  const tenantId = useSelectedTenantId();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ membershipId, payload }: { membershipId: string; payload: MembershipRoleChange }) =>
      api.changeMembershipRole(membershipId, payload),
    onSuccess: () => invalidateMemberships(queryClient, tenantId),
  });
}

export function useDeactivateMembership() {
  const tenantId = useSelectedTenantId();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (membershipId: string) => api.deactivateMembership(membershipId),
    onSuccess: () => invalidateMemberships(queryClient, tenantId),
  });
}

export function useReactivateMembership() {
  const tenantId = useSelectedTenantId();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (membershipId: string) => api.reactivateMembership(membershipId),
    onSuccess: () => invalidateMemberships(queryClient, tenantId),
  });
}
