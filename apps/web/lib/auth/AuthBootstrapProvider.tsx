"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { createContext, useCallback, useContext, useMemo, useState } from "react";
import type { ReactNode } from "react";

import { fetchAuthBootstrap, selectTenant as postSelectTenant } from "@/lib/auth/fetchAuthBootstrap";
import type { AuthBootstrap, TenantMembership } from "@/lib/auth/types";
import { queryKeys } from "@/lib/query/keys";

interface AuthBootstrapContextValue {
  bootstrap: AuthBootstrap | undefined;
  isLoading: boolean;
  selectedTenant: TenantMembership | null;
  /** Explicitly selects a tenant: POSTs to /api/tenant/select (which
   * fresh-verifies membership server-side), then -- only once that
   * succeeds -- clears every tenant-scoped cache entry and reseeds the
   * bootstrap with the server's fresh response. Callers are responsible
   * for navigating to /farms afterwards (see AppShell/TenantSelector,
   * select-tenant page) -- this function only owns auth/cache state. */
  selectTenant: (tenantId: string) => Promise<{ ok: boolean }>;
  isSwitchingTenant: boolean;
  /** Explicit, on-demand bootstrap refresh (AUTH-001B3) -- used by
   * /access-denied's "Check again" action and the bootstrap-error retry
   * action. Never polled/called automatically; AuthGate reacts to
   * whatever the resulting bootstrap.status turns out to be. */
  refetchBootstrap: () => Promise<void>;
}

const AuthBootstrapContext = createContext<AuthBootstrapContextValue | null>(null);

export function AuthBootstrapProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const [isSwitchingTenant, setIsSwitchingTenant] = useState(false);

  const query = useQuery({
    queryKey: queryKeys.authBootstrap(),
    queryFn: ({ signal }) => fetchAuthBootstrap(signal),
    // Explicit invalidation only (login, logout, tenant switch) -- never
    // polled/refetched on a timer or on every navigation.
    staleTime: Infinity,
  });

  const selectTenant = useCallback(
    async (tenantId: string): Promise<{ ok: boolean }> => {
      setIsSwitchingTenant(true);
      try {
        const result = await postSelectTenant(tenantId);
        // Clear FIRST, unconditionally: no tenant-scoped cache entry from
        // whatever tenant was previously active may survive into the next
        // render, even a success case where the new tenant differs from
        // the old one only by which farms/batches it has.
        queryClient.clear();
        if (result.ok) {
          queryClient.setQueryData(queryKeys.authBootstrap(), result.bootstrap);
          return { ok: true };
        }
        // clear() also removed the bootstrap entry itself -- reseed via a
        // real refetch so the app never sits on an empty/undefined
        // bootstrap after a failed switch attempt.
        await queryClient.invalidateQueries({ queryKey: queryKeys.authBootstrap() });
        return { ok: false };
      } finally {
        setIsSwitchingTenant(false);
      }
    },
    [queryClient],
  );

  const bootstrap = query.data;
  const selectedTenant = useMemo(() => {
    if (!bootstrap?.selectedTenantId) return null;
    return bootstrap.memberships.find((m) => m.tenantId === bootstrap.selectedTenantId) ?? null;
  }, [bootstrap]);

  const refetchBootstrap = useCallback(async () => {
    await query.refetch();
  }, [query]);

  const value: AuthBootstrapContextValue = {
    bootstrap,
    isLoading: query.isLoading,
    selectedTenant,
    selectTenant,
    isSwitchingTenant,
    refetchBootstrap,
  };

  return <AuthBootstrapContext.Provider value={value}>{children}</AuthBootstrapContext.Provider>;
}

export function useAuthBootstrap(): AuthBootstrapContextValue {
  const ctx = useContext(AuthBootstrapContext);
  if (!ctx) {
    throw new Error("useAuthBootstrap must be used within an AuthBootstrapProvider");
  }
  return ctx;
}
