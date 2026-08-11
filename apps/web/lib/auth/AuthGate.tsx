"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect } from "react";
import type { ReactNode } from "react";

import { ErrorState } from "@/components/ErrorState";
import { LoadingSkeleton } from "@/components/LoadingSkeleton";
import { useAuthBootstrap } from "@/lib/auth/AuthBootstrapProvider";
import { classifyRoute, decideRouteAccess, resolveAuthPhase } from "@/lib/auth/route-access";
import { AppError } from "@/lib/errors/adapter";

function NeutralLoadingState() {
  return (
    <div className="mx-auto max-w-lg px-4 py-16">
      <LoadingSkeleton rows={3} label="Loading" />
    </div>
  );
}

function AuthGateInner({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const router = useRouter();
  const { bootstrap, isLoading, refetchBootstrap } = useAuthBootstrap();

  const search = searchParams.toString() ? `?${searchParams.toString()}` : "";
  const routeClass = classifyRoute(pathname);
  const phase = resolveAuthPhase(bootstrap, isLoading);
  const decision = decideRouteAccess({ routeClass, phase, pathname, search });

  useEffect(() => {
    if (decision.kind === "redirect") {
      router.replace(decision.to);
    }
  }, [decision, router]);

  if (decision.kind === "allow") {
    return <>{children}</>;
  }

  if (decision.kind === "error") {
    return (
      <div className="mx-auto max-w-lg px-4 py-16">
        <ErrorState
          error={new AppError("server_error", "Unable to load CMP access. Try again.")}
          onRetry={() => {
            void refetchBootstrap();
          }}
        />
      </div>
    );
  }

  // "loading", or a redirect that has not yet navigated away -- protected/
  // gated content must never render during either.
  return <NeutralLoadingState />;
}

/**
 * The single central route gate (AUTH-001B3). Consumes
 * AuthBootstrapProvider's existing state only -- introduces no new
 * bootstrap/network request. Mounted once, wrapping every page, inside
 * Providers. `useSearchParams()` requires a Suspense boundary; its
 * fallback is the same neutral loading state shown while bootstrap
 * itself is loading, so there is no visible difference between the two.
 */
export function AuthGate({ children }: { children: ReactNode }) {
  return (
    <Suspense fallback={<NeutralLoadingState />}>
      <AuthGateInner>{children}</AuthGateInner>
    </Suspense>
  );
}
