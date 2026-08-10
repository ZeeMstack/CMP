"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";

import { AuthBootstrapProvider } from "@/lib/auth/AuthBootstrapProvider";

export function Providers({ children }: { children: React.ReactNode }) {
  const [queryClient] = useState(() => new QueryClient());
  return (
    <QueryClientProvider client={queryClient}>
      <AuthBootstrapProvider>{children}</AuthBootstrapProvider>
    </QueryClientProvider>
  );
}
