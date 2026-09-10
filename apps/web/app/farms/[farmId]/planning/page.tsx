"use client";

import { PlusCircle } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";

import { Breadcrumbs } from "@/components/Breadcrumbs";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { LoadingSkeleton } from "@/components/LoadingSkeleton";
import { PageHeader } from "@/components/PageHeader";
import { RequirementsTable } from "@/components/planning/RequirementsTable";
import { SeedingProgramTable } from "@/components/planning/SeedingProgramTable";
import { Tabs } from "@/components/ui/Tabs";
import { useProductionRequirements, useSeedingProgramLines } from "@/lib/query/hooks";

type PlanningTab = "requirements" | "seeding-program";

export default function PlanningPage() {
  const { farmId } = useParams<{ farmId: string }>();
  const [tab, setTab] = useState<PlanningTab>("requirements");

  const requirementsQuery = useProductionRequirements(farmId);
  const linesQuery = useSeedingProgramLines(farmId);

  return (
    <div>
      <PageHeader
        title="Planning"
        breadcrumbs={<Breadcrumbs items={[{ label: "Home", href: `/farms/${farmId}` }, { label: "Planning" }]} />}
        description="What crop do we need, how much, by when — and what are we planning to sow to cover it."
        actions={
          tab === "requirements" ? (
            <Link
              href={`/farms/${farmId}/planning/requirements/new`}
              className="flex min-h-11 items-center gap-1.5 rounded-md bg-wl-brand px-3 text-sm font-medium text-wl-text-on-brand hover:bg-wl-brand-hover focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-wl-focus"
            >
              <PlusCircle aria-hidden="true" className="h-4 w-4" />
              Production requirement
            </Link>
          ) : undefined
        }
      />

      <Tabs
        aria-label="Planning"
        activeId={tab}
        onChange={(id) => setTab(id as PlanningTab)}
        tabs={[
          { id: "requirements", label: "Requirements" },
          { id: "seeding-program", label: "Seeding Program" },
        ]}
      />

      <div className="mt-4">
        {tab === "requirements" && (
          <>
            {requirementsQuery.isLoading && <LoadingSkeleton rows={4} label="Loading production requirements" />}
            {requirementsQuery.error && (
              <ErrorState error={requirementsQuery.error} onRetry={() => requirementsQuery.refetch()} />
            )}
            {requirementsQuery.data && requirementsQuery.data.length === 0 && (
              <EmptyState
                title="No production requirements yet."
                description="Create one to record how much of a crop the farm needs to produce, and by when."
                action={
                  <Link
                    href={`/farms/${farmId}/planning/requirements/new`}
                    className="mt-2 flex min-h-11 items-center gap-1.5 rounded-md bg-wl-brand px-3 text-sm font-medium text-wl-text-on-brand hover:bg-wl-brand-hover"
                  >
                    <PlusCircle aria-hidden="true" className="h-4 w-4" />
                    Production requirement
                  </Link>
                }
              />
            )}
            {requirementsQuery.data && requirementsQuery.data.length > 0 && (
              <RequirementsTable requirements={requirementsQuery.data} farmId={farmId} />
            )}
          </>
        )}

        {tab === "seeding-program" && (
          <>
            {linesQuery.isLoading && <LoadingSkeleton rows={4} label="Loading the seeding program" />}
            {linesQuery.error && <ErrorState error={linesQuery.error} onRetry={() => linesQuery.refetch()} />}
            {linesQuery.data && linesQuery.data.length === 0 && (
              <EmptyState
                title="No planned sowings yet."
                description="Add a plan line from a Production Requirement to schedule a planned sowing against it."
              />
            )}
            {linesQuery.data && linesQuery.data.length > 0 && (
              <SeedingProgramTable lines={linesQuery.data} farmId={farmId} />
            )}
          </>
        )}
      </div>
    </div>
  );
}
