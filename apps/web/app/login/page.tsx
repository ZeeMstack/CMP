"use client";

import { useSearchParams } from "next/navigation";
import { Suspense } from "react";

import { sanitizeReturnTo } from "@/lib/auth/return-to";

/**
 * Minimal CMP login page (AUTH-001B1, returnTo wired in AUTH-001B3).
 * Deliberately no credential form -- Auth0 Universal Login performs all
 * credential entry; this page only links into the SDK-owned /auth/login
 * route, passing along a sanitized local returnTo so the user lands back
 * where they were headed. `AuthGate` is what gets an already-
 * authenticated visitor off this page -- this component itself only
 * ever renders while genuinely unauthenticated.
 */
function LoginContent() {
  const searchParams = useSearchParams();
  const returnTo = sanitizeReturnTo(searchParams.get("returnTo"));
  const signInHref = `/auth/login?returnTo=${encodeURIComponent(returnTo)}`;

  return (
    <div className="mx-auto flex min-h-screen max-w-sm flex-col items-center justify-center px-4 text-center">
      <h1 className="text-2xl font-semibold text-brand-700">GrowCMP</h1>
      <p className="mt-1 text-sm text-ink-muted">Commercial Hydroponic Operations</p>
      <a
        href={signInHref}
        className="mt-8 inline-flex min-h-11 items-center justify-center rounded-md bg-brand-700 px-6 text-sm font-medium text-white hover:bg-brand-800 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-600"
      >
        Sign in
      </a>
    </div>
  );
}

function LoginFallback() {
  return (
    <div className="mx-auto flex min-h-screen max-w-sm flex-col items-center justify-center px-4 text-center">
      <h1 className="text-2xl font-semibold text-brand-700">GrowCMP</h1>
      <p className="mt-1 text-sm text-ink-muted">Commercial Hydroponic Operations</p>
    </div>
  );
}

export default function LoginPage() {
  return (
    <Suspense fallback={<LoginFallback />}>
      <LoginContent />
    </Suspense>
  );
}
