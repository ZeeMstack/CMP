"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { useAuthBootstrap } from "@/lib/auth/AuthBootstrapProvider";
import { performSignOut } from "@/lib/auth/logout";

/**
 * Shown for both `not_provisioned` and zero-membership authenticated
 * states (AUTH-001B3) -- deliberately generic wording either way; never
 * reveals which of "no user row", "inactive user", "wrong identity
 * binding", or "zero memberships" applies (see AuthGate/route-access.ts
 * for how those states are distinguished server/route-side without
 * exposing the distinction to the user).
 */
export default function AccessDeniedPage() {
  const { bootstrap, refetchBootstrap } = useAuthBootstrap();
  const queryClient = useQueryClient();
  const [isChecking, setIsChecking] = useState(false);
  const [isSigningOut, setIsSigningOut] = useState(false);

  async function handleCheckAgain() {
    setIsChecking(true);
    try {
      // Reconciliation (0/1/many-membership handling) and any resulting
      // navigation are AuthGate's job, reacting to the refreshed
      // bootstrap.status -- this action only asks for a fresh read.
      await refetchBootstrap();
    } finally {
      setIsChecking(false);
    }
  }

  async function handleSignOut() {
    setIsSigningOut(true);
    await performSignOut(queryClient);
  }

  return (
    <div className="mx-auto max-w-lg px-4 py-16 text-center">
      <h1 className="text-xl font-semibold text-ink">Access not provisioned</h1>
      <p className="mt-3 text-sm text-ink-muted">
        Your sign-in was successful, but your account does not currently have access to a CMP workspace.
      </p>
      {bootstrap?.user && (
        <p className="mt-3 text-xs text-ink-muted">Signed in as {bootstrap.user.email}</p>
      )}
      <div className="mt-8 flex justify-center gap-3">
        <button
          type="button"
          onClick={handleCheckAgain}
          disabled={isChecking || isSigningOut}
          className="min-h-11 rounded-md bg-brand-700 px-4 text-sm font-medium text-white hover:bg-brand-800 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-600 disabled:opacity-60"
        >
          {isChecking ? "Checking…" : "Check again"}
        </button>
        <button
          type="button"
          onClick={handleSignOut}
          disabled={isChecking || isSigningOut}
          className="min-h-11 rounded-md border border-border-subtle px-4 text-sm font-medium text-ink hover:bg-surface-subtle focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-600 disabled:opacity-60"
        >
          Sign out
        </button>
      </div>
    </div>
  );
}
