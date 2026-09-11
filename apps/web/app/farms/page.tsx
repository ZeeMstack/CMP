"use client";

import { PlusCircle } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { LoadingSkeleton } from "@/components/LoadingSkeleton";
import { useAuthBootstrap } from "@/lib/auth/AuthBootstrapProvider";
import { useFarms } from "@/lib/query/hooks";

export default function FarmsPage() {
  const { bootstrap, isLoading: bootstrapLoading } = useAuthBootstrap();
  const { data: farms, isLoading, error, refetch } = useFarms();
  const router = useRouter();

  useEffect(() => {
    if (farms && farms.length === 1) {
      router.replace(`/farms/${farms[0].id}`);
    }
  }, [farms, router]);

  if (bootstrapLoading) {
    return (
      <div className="mx-auto max-w-lg px-4 py-16">
        <LoadingSkeleton rows={3} label="Loading" />
      </div>
    );
  }

  // GET /farms must never be issued before a tenant is selected -- this
  // hook is `enabled: false` in that case (see lib/query/hooks.ts), so
  // this branch is reached instead of a query ever firing.
  if (!bootstrap?.selectedTenantId) {
    if (bootstrap && bootstrap.memberships.length > 1) {
      return (
        <div className="mx-auto max-w-lg px-4 py-16">
          <EmptyState
            title="Choose a tenant"
            description="Select which tenant you want to work in before continuing."
          />
          <Link
            href="/select-tenant"
            className="mt-4 inline-flex min-h-11 items-center justify-center rounded-lg bg-wl-brand px-4 text-sm font-medium text-wl-text-on-brand hover:bg-wl-brand-hover focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-wl-focus"
          >
            Select tenant
          </Link>
        </div>
      );
    }
    // Authenticated with zero memberships, or unauthenticated/
    // not_provisioned/error -- B3 owns the polished routing/access-denied
    // UX for each of these. B2 shows a truthful, minimal state here
    // rather than ever rendering a misleading "No farms available".
    return (
      <div className="mx-auto max-w-lg px-4 py-16">
        <EmptyState
          title="No tenant access"
          description="Your account is not yet associated with any tenant. Contact an administrator."
        />
      </div>
    );
  }

  if (isLoading) {
    return (
      <div className="mx-auto max-w-lg px-4 py-16">
        <LoadingSkeleton rows={3} label="Loading farms" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="mx-auto max-w-lg px-4 py-16">
        <ErrorState error={error} onRetry={() => refetch()} />
      </div>
    );
  }

  if (!farms || farms.length === 0) {
    return (
      <div className="mx-auto max-w-lg px-4 py-16">
        <EmptyState
          title="No farms have been set up for this tenant yet."
          description="Create the first Farm to start configuring its physical structure."
          action={
            <Link
              href="/farms/new"
              className="mt-2 flex min-h-11 items-center gap-1.5 rounded-lg bg-wl-brand px-4 text-sm font-medium text-wl-text-on-brand hover:bg-wl-brand-hover focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-wl-focus"
            >
              <PlusCircle aria-hidden="true" className="h-4 w-4" />
              Create Farm
            </Link>
          }
        />
      </div>
    );
  }

  if (farms.length === 1) {
    // Redirect is in flight (see effect above); avoid flashing the picker.
    return null;
  }

  return (
    <div className="mx-auto max-w-lg px-4 py-16">
      <div className="mb-6 flex items-start justify-between gap-3">
        <div>
          <h1 className="mb-1 text-xl font-semibold text-wl-text">CMP</h1>
          <p className="text-sm text-wl-text-secondary">Choose a farm.</p>
        </div>
        <Link
          href="/farms/new"
          className="flex min-h-11 shrink-0 items-center gap-1.5 rounded-lg border border-wl-border-strong bg-wl-surface-raised px-3 text-sm font-medium text-wl-text hover:bg-wl-surface-hover focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-wl-focus"
        >
          <PlusCircle aria-hidden="true" className="h-4 w-4" />
          Create Farm
        </Link>
      </div>
      <ul className="space-y-2">
        {farms.map((farm) => (
          <li key={farm.id}>
            <Link
              href={`/farms/${farm.id}`}
              className="block min-h-11 rounded-lg border border-wl-border bg-wl-surface-raised px-4 py-3 hover:border-wl-brand hover:bg-wl-brand-subtle focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-wl-focus"
            >
              <span className="font-medium text-wl-text">{farm.name}</span>
              <span className="ml-2 text-sm text-wl-text-secondary">{farm.code}</span>
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}
