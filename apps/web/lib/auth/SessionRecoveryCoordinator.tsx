"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";

import { useAuthBootstrap } from "@/lib/auth/AuthBootstrapProvider";
import { fetchAuthBootstrap } from "@/lib/auth/fetchAuthBootstrap";
import { registerSessionRecoveryHandler, resetSessionRecoveryDedupe } from "@/lib/auth/sessionRecovery";
import { queryKeys } from "@/lib/query/keys";

/**
 * Renders nothing -- registers the handler `lib/api/client.ts` invokes
 * via `triggerSessionRecovery()` on any tenant-scoped business 401
 * (AUTH-001B3). Mounted once near the app root.
 *
 * PILOT-BLOCKER-008 CTO-review closure (session-expiry redirect-back
 * defect): this component used to ALSO own navigation (`router.replace`
 * to `/login?returnTo=...`) immediately after `queryClient.clear()`. Two
 * problems with that, both confirmed by tracing real renders:
 *
 * 1. A bare `clear()` never forced `AuthBootstrapProvider`'s actively-
 *    observed bootstrap query to actually refetch before this function
 *    returned (confirmed: `/api/auth/bootstrap` was called exactly once
 *    across an entire recovery sequence), so `AuthGate` could still
 *    observe stale "authenticated" data on the new `/login` pathname and
 *    bounce straight back to `returnTo`.
 * 2. Fixing #1 with an explicit authoritative `fetchQuery` + `clear()` +
 *    `setQueryData()` sequence, then navigating immediately afterward,
 *    STILL raced one layer deeper: TanStack Query's `notifyManager`
 *    batches observer notifications onto a microtask, so `AuthGate`'s
 *    very next render -- triggered synchronously by this same function's
 *    own `router.replace()` call -- could still read `useAuthBootstrap()`
 *    as the OLD "authenticated" object, despite `queryClient.getQueryData()`
 *    already reading back the correct fresh value at that exact moment.
 *    No fixed number of extra `await`s is a principled fix for that.
 *
 * The actual fix: stop owning navigation here at all. `AuthGate` is
 * already "the single central route gate" (its own docstring) and already
 * redirects an unauthenticated caller off any protected route, using ITS
 * OWN live `usePathname()`/`useSearchParams()` as `returnTo`
 * (`lib/auth/route-access.ts`'s `case "protected": case "unauthenticated"`
 * branch, unmodified) -- and since nothing navigates away from the failed
 * page during the recheck below, that live pathname/search IS the
 * original protected destination the whole time. Once this component
 * writes the authoritative recheck into the SAME bootstrap query
 * `AuthGate` observes, `AuthGate`'s own reactive render picks up the
 * change on some later render -- however many microtask hops TanStack's
 * notification takes, because `bootstrap` is a normal React value it
 * re-renders on -- and performs the (single, non-racing) redirect itself.
 * This also means a false-positive business 401 (the recheck genuinely,
 * repeatedly confirms the session is still valid) never forces a
 * navigation at all: `AuthGate` simply keeps rendering "allow" for a
 * still-"ready" phase, exactly as it always has.
 *
 * `clear()` + `setQueryData()` (mirroring the exact primitives
 * `AuthBootstrapProvider.tsx`'s own `selectTenant()` already uses for the
 * analogous tenant-switch cache-flash problem) still happen, so stale
 * tenant-scoped data never survives a session expiry.
 *
 * `triggerSessionRecovery`'s dedupe latch is set synchronously BEFORE this
 * (now-async) handler is ever invoked (see `sessionRecovery.ts`), so a
 * second concurrent 401 arriving while this handler is still in flight is
 * still correctly ignored.
 */
export function SessionRecoveryCoordinator(): null {
  const queryClient = useQueryClient();
  const { bootstrap } = useAuthBootstrap();

  useEffect(() => {
    // `returnToPath` is accepted for signature/documentation continuity
    // with `triggerSessionRecovery`'s callers (`lib/api/client.ts` captures
    // the exact failed page at the moment of the 401) but is no longer
    // used to build a navigation target here -- see the module docstring
    // for why that responsibility now belongs entirely to `AuthGate`.
    registerSessionRecoveryHandler(async (_returnToPath) => {
      const bootstrapKey = queryKeys.authBootstrap();
      const authoritativeBootstrap = await queryClient.fetchQuery({
        queryKey: bootstrapKey,
        queryFn: ({ signal }) => fetchAuthBootstrap(signal),
      });

      queryClient.clear();
      queryClient.setQueryData(bootstrapKey, authoritativeBootstrap);
    });
    return () => registerSessionRecoveryHandler(null);
  }, [queryClient]);

  useEffect(() => {
    if (bootstrap?.status === "authenticated") {
      resetSessionRecoveryDedupe();
    }
  }, [bootstrap?.status]);

  return null;
}
