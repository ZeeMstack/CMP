"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";

import { AuthBootstrapProvider } from "@/lib/auth/AuthBootstrapProvider";
import { AuthGate } from "@/lib/auth/AuthGate";
import { SessionRecoveryCoordinator } from "@/lib/auth/SessionRecoveryCoordinator";
import { shouldRetryQuery } from "@/lib/query/retry";

export function Providers({ children }: { children: React.ReactNode }) {
  const [queryClient] = useState(
    () => new QueryClient({ defaultOptions: { queries: { retry: shouldRetryQuery } } }),
  );
  return (
    <QueryClientProvider client={queryClient}>
      <AuthBootstrapProvider>
        <SessionRecoveryCoordinator />
        <AuthGate>{children}</AuthGate>
      </AuthBootstrapProvider>
    </QueryClientProvider>
  );
}
