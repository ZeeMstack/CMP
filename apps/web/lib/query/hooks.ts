"use client";

import { useQuery } from "@tanstack/react-query";

import * as api from "@/lib/api/client";
import { queryKeys } from "@/lib/query/keys";

/** staleTime tiers -- not every resource changes at the same rate. Farm and
 * location-hierarchy data is close to reference data for a pilot; batch
 * lists/detail reflect day-to-day operations and should refresh sooner. */
const STALE_REFERENCE_MS = 5 * 60_000;
const STALE_LIST_MS = 60_000;
const STALE_DETAIL_MS = 30_000;

export function useFarms() {
  return useQuery({
    queryKey: queryKeys.farms(),
    queryFn: ({ signal }) => api.listFarms(signal),
    staleTime: STALE_REFERENCE_MS,
  });
}

export function useFarm(farmId: string) {
  return useQuery({
    queryKey: queryKeys.farm(farmId),
    queryFn: ({ signal }) => api.getFarm(farmId, signal),
    staleTime: STALE_REFERENCE_MS,
  });
}

export function useLocationsTree(farmId: string) {
  return useQuery({
    queryKey: queryKeys.locationsTree(farmId),
    queryFn: ({ signal }) => api.getLocationsTree(farmId, signal),
    staleTime: STALE_REFERENCE_MS,
  });
}

/** On-demand only -- callers pass `enabled: false` until a structural
 * branch is actually expanded. One request per independently-expanded
 * root; React Query's cache (keyed on `locationId`) prevents re-fetching
 * the same root twice. */
export function useLocationSubtreeOccupancy(farmId: string, locationId: string, enabled: boolean) {
  return useQuery({
    queryKey: queryKeys.locationSubtreeOccupancy(farmId, locationId),
    queryFn: ({ signal }) => api.getLocationSubtreeOccupancy(farmId, locationId, signal),
    staleTime: STALE_DETAIL_MS,
    enabled,
  });
}

export function useOperationalSummary(farmId: string, state: "active" | "all") {
  return useQuery({
    queryKey: queryKeys.operationalSummary(farmId, state),
    queryFn: ({ signal }) => api.getOperationalSummary(farmId, state, signal),
    staleTime: STALE_LIST_MS,
  });
}

export function useBatchOperationalContext(farmId: string, batchId: string) {
  return useQuery({
    queryKey: queryKeys.batchOperationalContext(farmId, batchId),
    queryFn: ({ signal }) => api.getBatchOperationalContext(farmId, batchId, signal),
    staleTime: STALE_DETAIL_MS,
  });
}

export function useCropBatch(farmId: string, batchId: string) {
  return useQuery({
    queryKey: queryKeys.cropBatch(farmId, batchId),
    queryFn: ({ signal }) => api.getCropBatch(farmId, batchId, signal),
    staleTime: STALE_DETAIL_MS,
  });
}

export function useStageHistory(farmId: string, batchId: string) {
  return useQuery({
    queryKey: queryKeys.stageHistory(farmId, batchId),
    queryFn: ({ signal }) => api.getStageHistory(farmId, batchId, signal),
    staleTime: STALE_DETAIL_MS,
  });
}

export function useBatchLineage(farmId: string, batchId: string) {
  return useQuery({
    queryKey: queryKeys.batchLineage(farmId, batchId),
    queryFn: ({ signal }) => api.getBatchLineage(farmId, batchId, signal),
    staleTime: STALE_DETAIL_MS,
  });
}

export function useQualityHolds(farmId: string, batchId: string) {
  return useQuery({
    queryKey: queryKeys.qualityHolds(farmId, batchId),
    queryFn: ({ signal }) => api.getQualityHolds(farmId, batchId, signal),
    staleTime: STALE_DETAIL_MS,
  });
}
