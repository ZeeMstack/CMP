"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { useAuthBootstrap } from "@/lib/auth/AuthBootstrapProvider";
import { sanitizeReturnTo } from "@/lib/auth/return-to";
import { registerSessionRecoveryHandler, resetSessionRecoveryDedupe } from "@/lib/auth/sessionRecovery";

/**
 * Renders nothing -- registers the handler `lib/api/client.ts` invokes
 * via `triggerSessionRecovery()` on any tenant-scoped business 401
 * (AUTH-001B3). Mounted once near the app root.
 *
 * On recovery: clears the QueryClient (removes stale tenant-scoped data
 * *and* the now-incorrect cached bootstrap, matching B2's own
 * tenant-switch pattern), then replaces the current page with
 * `/login?returnTo=<safe path>` -- never a `push`, so Back does not
 * bounce between the failed page and /login.
 */
export function SessionRecoveryCoordinator(): null {
  const queryClient = useQueryClient();
  const router = useRouter();
  const { bootstrap } = useAuthBootstrap();

  useEffect(() => {
    registerSessionRecoveryHandler((returnToPath) => {
      queryClient.clear();
      const safeReturnTo = sanitizeReturnTo(returnToPath);
      router.replace(`/login?returnTo=${encodeURIComponent(safeReturnTo)}`);
    });
    return () => registerSessionRecoveryHandler(null);
  }, [queryClient, router]);

  useEffect(() => {
    if (bootstrap?.status === "authenticated") {
      resetSessionRecoveryDedupe();
    }
  }, [bootstrap?.status]);

  return null;
}
