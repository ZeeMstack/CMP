"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { LoadingSkeleton } from "@/components/LoadingSkeleton";
import { useFarms } from "@/lib/query/hooks";

export default function FarmsPage() {
  const { data: farms, isLoading, error, refetch } = useFarms();
  const router = useRouter();

  useEffect(() => {
    if (farms && farms.length === 1) {
      router.replace(`/farms/${farms[0].id}`);
    }
  }, [farms, router]);

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
          title="No farms available"
          description="This pilot identity has no accessible farms. Contact an administrator."
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
      <h1 className="mb-1 text-xl font-semibold text-ink">CMP</h1>
      <p className="mb-6 text-sm text-ink-muted">Choose a farm.</p>
      <ul className="space-y-2">
        {farms.map((farm) => (
          <li key={farm.id}>
            <Link
              href={`/farms/${farm.id}`}
              className="block min-h-11 rounded-lg border border-border-subtle bg-surface px-4 py-3 hover:border-brand-300 hover:bg-brand-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-600"
            >
              <span className="font-medium text-ink">{farm.name}</span>
              <span className="ml-2 text-sm text-ink-muted">{farm.code}</span>
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}
