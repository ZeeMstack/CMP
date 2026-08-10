import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

import { AuthBootstrapProvider } from "@/lib/auth/AuthBootstrapProvider";
import type { AuthBootstrap } from "@/lib/auth/types";
import { queryKeys } from "@/lib/query/keys";

export const TEST_TENANT_ID = "11111111-1111-1111-1111-111111111111";

/** A plausible, already-authenticated, single-tenant bootstrap -- the
 * default for component tests that don't care about tenant/auth state
 * themselves, so tenant-scoped hooks (which all read the active tenant
 * from AuthBootstrapProvider) resolve to a real tenant id rather than
 * being permanently `enabled: false`. Pre-seeded directly into the
 * QueryClient's cache so no test ever triggers a real `fetch()` to
 * /api/auth/bootstrap. */
export const DEFAULT_TEST_BOOTSTRAP: AuthBootstrap = {
  status: "authenticated",
  user: { id: "test-user-id", email: "test@example.com", displayName: "Test User" },
  memberships: [{ tenantId: TEST_TENANT_ID, tenantCode: "TEST", tenantName: "Test Tenant", roleCode: "tenant_admin" }],
  selectedTenantId: TEST_TENANT_ID,
};

export function withQueryClient(children: ReactNode, bootstrap: AuthBootstrap | null = DEFAULT_TEST_BOOTSTRAP) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  if (bootstrap) {
    queryClient.setQueryData(queryKeys.authBootstrap(), bootstrap);
  }
  return (
    <QueryClientProvider client={queryClient}>
      <AuthBootstrapProvider>{children}</AuthBootstrapProvider>
    </QueryClientProvider>
  );
}
