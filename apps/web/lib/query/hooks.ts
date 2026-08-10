"use client";

import { useQuery } from "@tanstack/react-query";

import * as api from "@/lib/api/client";
import { useAuthBootstrap } from "@/lib/auth/AuthBootstrapProvider";
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
