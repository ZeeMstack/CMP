"use client";

import { useParams } from "next/navigation";
import type { ReactNode } from "react";

import { AppShell } from "@/components/AppShell";
import { ErrorState } from "@/components/ErrorState";
import { LoadingSkeleton } from "@/components/LoadingSkeleton";
import { useFarm } from "@/lib/query/hooks";

export default function FarmLayout({ children }: { children: ReactNode }) {
  const { farmId } = useParams<{ farmId: string }>();
  const { isLoading, error, refetch } = useFarm(farmId);

  if (isLoading) {
    return (
      <div className="mx-auto max-w-lg px-4 py-16">
        <LoadingSkeleton rows={3} label="Loading farm" />
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

  return <AppShell farmId={farmId}>{children}</AppShell>;
}
